import json
import os
import random
import shutil
import string
import zipfile
from operator import or_, and_
from urllib.parse import quote

from flask import render_template, jsonify, session, request, redirect, url_for, send_from_directory, send_file, \
    make_response
from werkzeug.utils import secure_filename

import settings as Config
from project import app, intergration
from project.models import *
from concurrent.futures import ThreadPoolExecutor
from project import email_send as Email

# 创建线程池执行器
executor = ThreadPoolExecutor(4)

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['DOWNLOAD_FOLDER'] = os.path.join(basedir, 'static/avatar')


@app.route('/upload_video', methods=['GET', 'POST'])
def upload_video():
    uid = session.get('uid')
    if uid is None:
        return redirect(url_for('login'))
    user = User.query.filter(User.user_id == uid).first()
    if request.method == "POST":
        check = request.form.get("inlineRadioOptions")
        model_name = request.form.get("name")
        describe = request.form.get("message")
        model_tag = request.form.get("model_tag")
        if str(check) == "video":
            video_folder_path = Config.video_folder_path
            image_folder_path = Config.image_folder_path
            file = request.files['file']
            filename = file.filename
            # 防止同时间上传相同名称的文件
            filename = filename.split('.')[0] + str(random.choice(string.ascii_letters)) + "." + \
                       filename.split('.')[1]
            type_check = str(filename).split(".")[1]
            type_check = type_check.lower()
            print(filename)
            print(type_check)
            # 判断是否上传的是图片
            if type_check not in ['mp4', 'm4v', 'mkv', 'webm', 'mov', 'avi', 'wmv', 'mpg', 'flv']:
                return redirect(url_for('fail'))
            # 判断是否存在相同名称的视频和图片文件夹
            video_check = os.path.join(video_folder_path, filename)
            pic_check = os.path.join(image_folder_path, filename)
            while os.path.exists(video_check) or os.path.exists(pic_check):
                filename = filename.split('.')[0] + str(random.choice(string.ascii_letters)) + "." + \
                           filename.split('.')[1]
                video_check = os.path.join(video_folder_path, filename)
                pic_check = os.path.join(image_folder_path, filename)
            # 检测视频长度是否过长
            video_duration_path = os.path.join(video_folder_path, filename)
            video_duration = intergration.get_video_duration(video_duration_path)
            if video_duration > 60:
                return redirect(url_for('fail'))
            # 存储视频文件
            file.save(os.path.join(video_folder_path, filename))
            # 异步执行脚本处理
            executor.submit(video_task, video_folder_path, image_folder_path, filename, uid, model_name, describe,
                            model_tag)
            return redirect(url_for('success'))
        elif str(check) == "pic":
            files = request.files.getlist('file')
            # 逐个存储文件
            image_folder_path = Config.image_folder_path
            # 创造一个新的文件夹来存储图片（用完后删）
            folder_name = "UserUploadImage-"
            for i in range(0, 5):
                folder_name += str(random.choice(string.ascii_letters))
            image_folder_path = os.path.join(image_folder_path, folder_name)
            while os.path.exists(image_folder_path):
                folder_name += str(random.choice(string.ascii_letters))
                image_folder_path = os.path.join(image_folder_path, folder_name)
            os.mkdir(image_folder_path)
            # 检测照片数量是否过多
            pic_num = len(files)
            if pic_num > 70:
                # 删除创造的空文件夹
                shutil.rmtree(image_folder_path)
                return redirect(url_for('fail'))
            for file in files:
                # 存储图片
                file.save(os.path.join(image_folder_path, file.filename))
                # 判断上传的文件是否全是图片
                type_check = str(file.filename).split('.')[1]
                type_check = type_check.lower()
                # 如果上传的文件中包含非照片文件，停止并删除文件夹
                if type_check not in ['jpg', 'png']:
                    try:
                        shutil.rmtree(image_folder_path)
                    except OSError:
                        pass
                    return redirect(url_for('fail'))
            # 异步执行脚本处理
            executor.submit(pic_task, image_folder_path, uid, model_name, describe, model_tag, folder_name = folder_name)
            return redirect(url_for('success'))
    return render_template('upload.html', user=user)


# 上传视频的脚本部分的执行
def video_task(video_folder_path, image_folder_path, filename, uid, model_name, describe, model_tag):
    # 提取视频中的帧并存储
    intergration.extra(video_folder_path, filename, image_folder_path, frequency=5)
    # 从image_path中随机选取一张图片作为cover
    model_cover_path = ''
    cover_folder_path = Config.cover_folder_path
    image_path = os.path.join(image_folder_path, filename.split(".")[0])
    for file in os.listdir(image_path):
        model_cover_path = os.path.join(cover_folder_path, file)
        while os.path.exists(model_cover_path):
            model_cover_path = model_cover_path.split('.')[0] + str(random.choice(string.ascii_letters)) + '.jpg'
        # 存储
        shutil.copy(os.path.join(image_path, file), model_cover_path)
        break
    # 只存储cover的filename，不然使用相对路径时比较麻烦
    model_cover_path = str(model_cover_path).split('covers')[1]
    model_cover_path = model_cover_path[1:]
    # 存储obj文件的文件夹
    model_path = Config.model_folder_path
    if not os.path.exists(model_path):
        os.mkdir(model_path)
    # 需要restruction的图片的文件夹
    image_path = os.path.join(image_folder_path, filename.split(".")[0])
    # 定义存储脚本的文件夹
    sh_path = Config.sh_folder_path
    # 定义临时存储脚本产生的文件的文件夹
    temp_file_path = Config.temp_folder_path
    # 防止冲突
    while os.path.exists(temp_file_path):
        temp_file_path += str(random.choice(string.ascii_letters))
    # 创造新的文件夹
    os.mkdir(temp_file_path)
    # 创造images文件夹
    os.mkdir(os.path.join(temp_file_path, 'images'))
    # 移动脚本文件到该文件夹中
    shutil.copy(os.path.join(sh_path, 'change.sh'), temp_file_path)
    # 将所有需要重构的图片移动到该文件夹中
    for file in os.listdir(image_path):
        shutil.copy(os.path.join(image_path, file), os.path.join(temp_file_path, 'images'))
    # 启动脚本
    # 这个脚本会在启动时暂停进程来做到异步，运行完成后会进行接下来的步骤
    os.system('sh ' + temp_file_path + '/change.sh')

    # 判断sh文件是否执行成功（成功则会生成obj文件）
    if not any(name.endswith(('.obj')) for name in os.listdir(temp_file_path)):
        # 递归删除之前中转的文件夹
        try:
            shutil.rmtree(temp_file_path)
        except OSError:
            pass
        # 删除存储图片的文件夹
        try:
            shutil.rmtree(image_path)
        except OSError:
            pass
        # 删除视频
        os.remove(os.path.join(video_folder_path, filename))
        return

    # 定义生成的文件的存储文件夹的名字
    model_folder_name = ""
    for i in range(0, 5):
        model_folder_name += str(random.choice(string.ascii_letters))
    # 定义文件夹的路径
    model_folder_path = os.path.join(model_path, model_folder_name)
    # 判断name是否重复
    while os.path.exists(model_folder_path):
        # 数据库中存储的是model_folder_name
        model_folder_name += str(random.choice(string.ascii_letters))
        model_folder_path = os.path.join(model_path, model_folder_name)
    # 创造文件夹
    os.mkdir(model_folder_path)
    # 提取mtl，obj，jpg和png文件并存储
    needed_type = ['mtl', 'obj', 'jpg', 'png']
    for file in os.listdir(temp_file_path):
        file_type = str(file).split('.')
        if len(file_type) == 2 and file_type[1] in needed_type:
            # 将模型文件移动到store文件夹中来存储
            shutil.copy(os.path.join(temp_file_path, file), model_folder_path)
    # 将模型的文件夹压缩成压缩文件，不然无法下载
    file_zip(model_folder_path)
    # 递归删除之前中转的文件夹
    try:
        shutil.rmtree(temp_file_path)
    except OSError:
        pass
    # 删除存储图片的文件夹
    try:
        shutil.rmtree(image_path)
    except OSError:
        pass
    # 删除视频(暂时保留视频)
    # os.remove(os.path.join(video_folder_path, filename))
    # 存储到数据库中
    model = Model(model_name=model_name, model_path=model_folder_name, user_id=uid, cover_path=model_cover_path,
                  describe=describe, model_tag=model_tag, video_path = filename)
    db.session.add(model)
    db.session.commit()


# 上传图像的脚本执行部分
def pic_task(image_folder_path, uid, model_name, describe, model_tag, folder_name):
    # 处理图片
    intergration.image_deal(image_folder_path)
    # 将随机一张图片作为model的cover
    model_cover_path = ''
    cover_folder_path = Config.cover_folder_path
    for file in os.listdir(image_folder_path):
        model_cover_path = os.path.join(cover_folder_path, file)
        while os.path.exists(model_cover_path):
            model_cover_path = model_cover_path.split('.')[0] + str(random.choice(string.ascii_letters)) + '.jpg'
        # 存储
        shutil.copy(os.path.join(image_folder_path, file), model_cover_path)
        break
    # 只存储cover的filename，不然使用相对路径时比较麻烦
    model_cover_path = str(model_cover_path).split('covers')[1]
    model_cover_path = model_cover_path[1:]
    # 存储obj文件的文件夹
    model_path = Config.model_folder_path
    if not os.path.exists(model_path):
        os.mkdir(model_path)
    # 需要restruction的图片的文件夹
    image_path = image_folder_path
    # 定义存储脚本的文件夹
    sh_path = Config.sh_folder_path
    # 定义临时存储脚本产生的文件的文件夹
    temp_file_path = Config.temp_folder_path
    # 防止冲突
    while os.path.exists(temp_file_path):
        temp_file_path += str(random.choice(string.ascii_letters))
    # 创造新的文件夹
    os.mkdir(temp_file_path)
    # 创造images文件夹
    os.mkdir(os.path.join(temp_file_path, 'images'))
    # 移动脚本文件到该文件夹中
    shutil.copy(os.path.join(sh_path, 'change.sh'), temp_file_path)
    # 将所有需要重构的图片移动到该文件夹中
    for file in os.listdir(image_path):
        shutil.copy(os.path.join(image_path, file), os.path.join(temp_file_path, 'images'))
    # 启动脚本
    # 这个脚本会在启动时暂停进程来做到异步，运行完成后会进行接下来的步骤
    os.system('sh ' + temp_file_path + '/change.sh')

    # 判断sh文件是否执行成功（成功则会生成obj文件）
    if not any(name.endswith(('.obj')) for name in os.listdir(temp_file_path)):
        # 递归删除之前中转的文件夹
        try:
            shutil.rmtree(temp_file_path)
        except OSError:
            pass
        # 删除存储图片的文件夹
        try:
            shutil.rmtree(image_path)
        except OSError:
            pass
        return

    # 定义生成的文件的存储文件夹的名字
    model_folder_name = ""
    for i in range(0, 5):
        model_folder_name += str(random.choice(string.ascii_letters))
    # 定义文件夹的路径
    model_folder_path = os.path.join(model_path, model_folder_name)
    # 判断name是否重复
    while os.path.exists(model_folder_path):
        model_folder_name += str(random.choice(string.ascii_letters))
        model_folder_path = os.path.join(model_path, model_folder_name)
    # 创造文件夹
    os.mkdir(model_folder_path)
    # 提取mtl，obj，jpg和png文件并存储
    needed_type = ['mtl', 'obj', 'jpg', 'png']
    for filename in os.listdir(temp_file_path):
        file_type = str(filename).split('.')
        if len(file_type) == 2 and file_type[1] in needed_type:
            # 将模型文件移动到store文件夹中来存储
            shutil.copy(os.path.join(temp_file_path, filename), model_folder_path)
    # 将模型的文件夹压缩成压缩文件，不然无法下载
    file_zip(model_folder_path)
    # 递归删除之前中转的文件夹
    try:
        shutil.rmtree(temp_file_path)
    except OSError:
        pass
    # 删除存储图片的文件夹(暂时保留原始数据)
    # try:
    #     shutil.rmtree(image_path)
    # except OSError:
    #     pass
    # 存储到数据库中
    model = Model(model_name=model_name, model_path=model_folder_name, user_id=uid, cover_path=model_cover_path,
                  describe=describe, model_tag=model_tag, image_path = folder_name)
    db.session.add(model)
    db.session.commit()


# 将文件夹压缩成压缩文件，不然无法下载文件夹
def file_zip(start_dir):
    start_dir = start_dir  # 要压缩的文件夹路径
    file_news = start_dir + '.zip'  # 压缩后文件夹的名字

    z = zipfile.ZipFile(file_news, 'w', zipfile.ZIP_DEFLATED)
    for dir_path, dir_names, file_names in os.walk(start_dir):
        f_path = dir_path.replace(start_dir, '')  # 这一句很重要，不replace的话，就从根目录开始复制
        f_path = f_path and f_path + os.sep or ''  # 实现当前文件夹以及包含的所有文件的压缩
        for filename in file_names:
            z.write(os.path.join(dir_path, filename), f_path + filename)
    z.close()
    return file_news


# test done
@app.route('/model_download/<filename>')
def model_download(filename):
    model_folder_path = Config.model_folder_path
    filename += '.zip'
    # filename = 'test1.mp4'
    response = make_response(send_from_directory(model_folder_path, filename))
    # 解决文件名无法是中文的问题
    response.headers["Content-Disposition"] = "attachment; filename={0}; filename*=utf-8''{0}".format(
        quote(filename))
    return response


# 模型展示
# test done in server
@app.route('/display/<model_id>')
def display(model_id):
    uid = session.get('uid')
    model = Model.query.filter(Model.model_id == model_id).first()
    if model is None:
        return redirect(url_for('blog'))
    folder_name = model.model_path
    obj_path = ''
    pic_path = ''
    # 得到文件夹的名字
    model_path = os.path.join(Config.model_folder_path, folder_name)
    for file in os.listdir(model_path):
        style = str(file).split('.')[1]
        if style == 'obj':
            # os.path.join中会添加‘\’作为连接符，这会导致无法找到文件
            # pic_path = os.path.join("../static/debug", file)
            obj_path = '../static/models/' + folder_name + '/' + file
        elif style in ['jpg', 'png']:
            pic_path = '../static/models/' + folder_name + '/' + file

    if uid is None:
        return render_template('threeFunction.html', title='OBJ', obj_path=obj_path, pic_path=pic_path)

    user = User.query.filter(User.user_id == uid).first()
    return render_template('threeFunction.html', title='OBJ', user=user, obj_path=obj_path, pic_path=pic_path)


@app.route('/qixi', methods=['GET', 'POST'])
def qixi():
    # 更新七夕活动的浏览量
    act = QiXiAct.query.all()
    if len(act) == 0:
        qixiAct = QiXiAct(views = 1, submit = 0)
        db.session.add(qixiAct)
        db.session.commit()
    else:
        act = QiXiAct.query.filter(QiXiAct.id == 1).first()
        act.views += 1
        db.session.commit()

    if request.method == "POST":
        user_email = request.form.get("email")
        model_name = request.form.get("name")
        describe = request.form.get("message")
        check = request.form.get("inlineRadioOptions")
        if str(check) == "video":
            video_folder_path = Config.video_folder_path
            image_folder_path = Config.image_folder_path
            file = request.files['file']
            filename = file.filename
            # 防止同时间上传相同名称的文件
            filename = filename.split('.')[0] + str(random.choice(string.ascii_letters)) + "." + \
                       filename.split('.')[1]
            type_check = str(filename).split(".")[1]
            type_check = type_check.lower()
            # 判断是否上传的是视频
            if type_check not in ['mp4', 'm4v', 'mkv', 'webm', 'mov', 'avi', 'wmv', 'mpg', 'flv']:
                return redirect(url_for('fail'))
            # 判断是否存在相同名称的视频和图片文件夹
            video_check = os.path.join(video_folder_path, filename)
            pic_check = os.path.join(image_folder_path, filename)
            while os.path.exists(video_check) or os.path.exists(pic_check):
                filename = filename.split('.')[0] + str(random.choice(string.ascii_letters)) + "." + \
                           filename.split('.')[1]
                video_check = os.path.join(video_folder_path, filename)
                pic_check = os.path.join(image_folder_path, filename)
            # 检测视频长度是否过长
            video_duration_path = os.path.join(video_folder_path, filename)
            video_duration = intergration.get_video_duration(video_duration_path)
            if video_duration > 60:
                return redirect(url_for('fail'))
            # 存储视频文件
            file.save(os.path.join(video_folder_path, filename))
            # 异步执行脚本处理
            executor.submit(video_task_qixi, video_folder_path, image_folder_path, filename, model_name, describe, user_email)
            return redirect(url_for('success'))
        elif str(check) == "pic":
            files = request.files.getlist('file')
            # 逐个存储文件
            image_folder_path = Config.image_folder_path
            # 创造一个新的文件夹来存储图片（用完后删）
            folder_name = "QiXiAct-"
            for i in range(0, 5):
                folder_name += str(random.choice(string.ascii_letters))
            image_folder_path = os.path.join(image_folder_path, folder_name)
            while os.path.exists(image_folder_path):
                folder_name += str(random.choice(string.ascii_letters))
                image_folder_path = os.path.join(image_folder_path, folder_name)
            os.mkdir(image_folder_path)
            # 检测照片数量是否过多
            pic_num = len(files)
            if pic_num > 70:
                # 删除之前创造的空文件夹
                shutil.rmtree(image_folder_path)
                return redirect(url_for('fail'))
            for file in files:
                # 存储图片
                file.save(os.path.join(image_folder_path, file.filename))
                # 判断上传的文件是否全是图片，
                type_check = str(file.filename).split('.')[1]
                type_check = type_check.lower()
                if type_check not in ['jpg', 'png']:
                    try:
                        shutil.rmtree(image_folder_path)
                    except OSError:
                        pass
                    return redirect(url_for('fail'))
            # 异步执行脚本处理
            executor.submit(pic_task_qixi, image_folder_path, model_name, describe, user_email, folder_name)
            return redirect(url_for('success'))
    return render_template('base_qixi.html')


# 上传视频的脚本部分的执行
def video_task_qixi(video_folder_path, image_folder_path, filename, model_name, describe, user_email):
    # 提取视频中的帧并存储
    intergration.extra(video_folder_path, filename, image_folder_path, frequency=5)
    # 存储obj文件的文件夹
    model_path = Config.model_folder_path
    if not os.path.exists(model_path):
        os.mkdir(model_path)
    # 需要restruction的图片的文件夹
    image_path = os.path.join(image_folder_path, filename.split(".")[0])
    # 定义存储脚本的文件夹
    sh_path = Config.sh_folder_path
    # 定义临时存储脚本产生的文件的文件夹
    temp_file_path = Config.temp_folder_path
    # 防止冲突
    while os.path.exists(temp_file_path):
        temp_file_path += str(random.choice(string.ascii_letters))
    # 创造新的文件夹
    os.mkdir(temp_file_path)
    # 创造images文件夹
    os.mkdir(os.path.join(temp_file_path, 'images'))
    # 移动脚本文件到该文件夹中
    shutil.copy(os.path.join(sh_path, 'change.sh'), temp_file_path)
    # 将所有需要重构的图片移动到该文件夹中
    for file in os.listdir(image_path):
        shutil.copy(os.path.join(image_path, file), os.path.join(temp_file_path, 'images'))
    # 启动脚本
    # 这个脚本会在启动时暂停进程来做到异步，运行完成后会进行接下来的步骤
    os.system('sh ' + temp_file_path + '/change.sh')

    # 判断sh文件是否执行成功（成功则会生成obj文件）
    if not any(name.endswith(('.obj')) for name in os.listdir(temp_file_path)):
        # 递归删除之前中转的文件夹
        try:
            shutil.rmtree(temp_file_path)
        except OSError:
            pass
        # 删除存储图片的文件夹
        try:
            shutil.rmtree(image_path)
        except OSError:
            pass
        # 删除视频
        os.remove(os.path.join(video_folder_path, filename))
        send_email_fail(user_email, model_name, describe)
        return

    # 定义生成的文件的存储文件夹的名字
    model_folder_name = ""
    for i in range(0, 5):
        model_folder_name += str(random.choice(string.ascii_letters))
    # 定义文件夹的路径
    model_folder_path = os.path.join(Config.qixi_model_folder_path, model_folder_name)
    # 判断name是否重复
    while os.path.exists(model_folder_path):
        # 数据库中存储的是model_folder_name
        model_folder_name += str(random.choice(string.ascii_letters))
        model_folder_path = os.path.join(Config.qixi_model_folder_path, model_folder_name)
    # 创造文件夹
    os.mkdir(model_folder_path)
    # 提取mtl，obj，jpg和png文件并存储
    needed_type = ['mtl', 'obj', 'jpg', 'png']
    for file in os.listdir(temp_file_path):
        file_type = str(file).split('.')
        if len(file_type) == 2 and file_type[1] in needed_type:
            # 将模型文件移动到store文件夹中来存储
            shutil.copy(os.path.join(temp_file_path, file), model_folder_path)
    # 将模型的文件夹压缩成压缩文件，不然无法下载
    file_zip(model_folder_path)
    # 递归删除之前中转的文件夹
    try:
        shutil.rmtree(temp_file_path)
    except OSError:
        pass
    # 删除存储图片的文件夹
    try:
        shutil.rmtree(image_path)
    except OSError:
        pass
    # 将视频转移到特定的文件夹
    filename_check = filename
    # 先对文件进行重命名，防止同时间有相同的文件在转移
    filename_check = filename_check.split('.')[0] + str(random.choice(string.ascii_letters)) + "." + \
                     filename_check.split('.')[1]
    while os.path.exists(os.path.join(Config.qixi_video_folder_path, filename_check)):
        filename_check = filename_check.split('.')[0] + str(random.choice(string.ascii_letters)) + "." + \
                   filename_check.split('.')[1]
    # 转移文件夹
    shutil.move(os.path.join(video_folder_path, filename), os.path.join(Config.qixi_video_folder_path, filename_check))
    # 发送模型重建成功的邮件
    send_email_with_files(user_email, model_name, describe, model_folder_name)
    # send_email_success(user_email, model_name, describe)
    # 更新七夕活动的提交量
    act = QiXiAct.query.filter(QiXiAct.id == 1).first()
    act.submit += 1
    db.session.commit()
    # 记录相关的信息
    qixi_record = QiXi(email = user_email, model_name = model_name, describe = describe, model_type = "video", model_path = filename)
    db.session.add(qixi_record)
    db.session.commit()


# 上传图像的脚本执行部分
def pic_task_qixi(image_folder_path, model_name, describe, user_email, folder_name):
    # 处理图片
    intergration.image_deal(image_folder_path)
    # 存储obj文件的文件夹
    model_path = Config.model_folder_path
    if not os.path.exists(model_path):
        os.mkdir(model_path)
    # 需要restruction的图片的文件夹
    image_path = image_folder_path
    # 定义存储脚本的文件夹
    sh_path = Config.sh_folder_path
    # 定义临时存储脚本产生的文件的文件夹
    temp_file_path = Config.temp_folder_path
    # 防止冲突
    while os.path.exists(temp_file_path):
        temp_file_path += str(random.choice(string.ascii_letters))
    # 创造新的文件夹
    os.mkdir(temp_file_path)
    # 创造images文件夹
    os.mkdir(os.path.join(temp_file_path, 'images'))
    # 移动脚本文件到该文件夹中
    shutil.copy(os.path.join(sh_path, 'change.sh'), temp_file_path)
    # 将所有需要重构的图片移动到该文件夹中
    for file in os.listdir(image_path):
        shutil.copy(os.path.join(image_path, file), os.path.join(temp_file_path, 'images'))
    # 启动脚本
    # 这个脚本会在启动时暂停进程来做到异步，运行完成后会进行接下来的步骤
    os.system('sh ' + temp_file_path + '/change.sh')

    # 判断sh文件是否执行成功（成功则会生成obj文件）
    if not any(name.endswith(('.obj')) for name in os.listdir(temp_file_path)):
        # 递归删除之前中转的文件夹
        try:
            shutil.rmtree(temp_file_path)
        except OSError:
            pass
        # 删除存储图片的文件夹
        try:
            shutil.rmtree(image_path)
        except OSError:
            pass
        send_email_fail(user_email, model_name, describe)
        return

    # 定义生成的文件的存储文件夹的名字
    model_folder_name = ""
    for i in range(0, 5):
        model_folder_name += str(random.choice(string.ascii_letters))
    # 定义文件夹的路径
    model_folder_path = os.path.join(Config.qixi_model_folder_path, model_folder_name)
    # 判断name是否重复
    while os.path.exists(model_folder_path):
        model_folder_name += str(random.choice(string.ascii_letters))
        model_folder_path = os.path.join(Config.qixi_model_folder_path, model_folder_name)
    # 创造文件夹
    os.mkdir(model_folder_path)
    # 提取mtl，obj，jpg和png文件并存储
    needed_type = ['mtl', 'obj', 'jpg', 'png']
    for filename in os.listdir(temp_file_path):
        file_type = str(filename).split('.')
        if len(file_type) == 2 and file_type[1] in needed_type:
            # 将模型文件移动到store文件夹中来存储
            shutil.copy(os.path.join(temp_file_path, filename), model_folder_path)
    # 将模型的文件夹压缩成压缩文件，不然无法下载
    file_zip(model_folder_path)
    # 递归删除之前中转的文件夹
    try:
        shutil.rmtree(temp_file_path)
    except OSError:
        pass
    # 转移文件夹
    filename_check = ""
    for i in range(0, 6):
        filename_check += str(random.choice(string.ascii_letters))
    while os.path.exists(os.path.join(Config.qixi_image_folder_path, filename_check)):
        filename_check += str(random.choice(string.ascii_letters))
    shutil.move(image_path, os.path.join(Config.qixi_image_folder_path, filename_check))
    # 发送模型重建成功的邮件
    send_email_with_files(user_email, model_name, describe, folder_name)
    # send_email_success(user_email, model_name, describe)
    # 更新七夕活动的提交量
    act = QiXiAct.query.filter(QiXiAct.id == 1).first()
    act.submit += 1
    db.session.commit()
    # 记录相关的信息
    qixi_record = QiXi(email=user_email, model_name=model_name, describe=describe, model_type="image",
                       model_path=folder_name)
    db.session.add(qixi_record)
    db.session.commit()


# 模型展示
# test done in server
@app.route('/qixi_display/<folder_name>')
def qixi_display(folder_name):
    obj_path = ''
    pic_path = ''
    # 得到文件夹的名字
    model_path = os.path.join(Config.qixi_model_folder_path, folder_name)
    for file in os.listdir(model_path):
        style = str(file).split('.')[1]
        if style == 'obj':
            # os.path.join中会添加‘\’作为连接符，这会导致无法找到文件
            # pic_path = os.path.join("../static/debug", file)
            obj_path = '../static/qixi/models/' + folder_name + '/' + file
        elif style in ['jpg', 'png']:
            pic_path = '../static/qixi/models/' + folder_name + '/' + file
    return render_template('threeFunction.html', title='OBJ', obj_path=obj_path, pic_path=pic_path)



@app.route('/test')
def test():
    user_email = "1375025739@qq.com"
    model_name = 'a'
    describe = 'b'
    folder_name = "xAPdm"
    send_email_with_files(user_email, model_name, describe, folder_name)
    return render_template('test.html')


# test done
def send_email_with_files(user_email, model_name, describe, folder_name):
    # Email.send_mail(receivers=([user_email]), subject='测试',
    #                 text=render_template('email/email_send_success.txt', folder_name = folder_name),
    #                 html=render_template('email/email_send_success.html', folder_name = folder_name),
    #                 file_path= 'static/models/' + folder_name + ".zip"
    #                 )
    zip_name =  folder_name + ".zip"
    file_path = os.path.join(Config.qixi_model_folder_path, zip_name)
    Email.send_mail_with_files(receivers=([user_email]), model_name = model_name, describe = describe,
                            file_path= file_path, folder_name = folder_name)



def send_email_success(user_email, model_name, describe):
    Email.send_mail_success(receivers=([user_email]), model_name = model_name, describe = describe)



# test done
def send_email_fail(user_email, model_name, describe):
    Email.send_mail_fail(receivers=([user_email]), model_name = model_name, describe = describe)


@app.route('/Comment', methods=['POST', 'GET'])
def comment():
    # 这里的exist都是通过前端来检查
    uid = session.get('uid')
    if uid is None:
        return jsonify(1)
    mid = request.form["model_id"]
    mid = int(mid)
    model = Model.query.filter(Model.model_id == mid).first()
    content = request.form["content"]
    disabled = True
    record = Comment(content=content, disabled=disabled, uid=uid, model=model, model_id=mid)
    db.session.add(record)
    db.session.commit()
    return jsonify(0)


@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/about_us')
def about_us():
    uid = session.get('uid')
    if uid is None:
        return render_template('about-us.html')
    user = User.query.filter(User.user_id == session['uid']).first()
    return render_template('about-us.html', user=user)


@app.route('/logout')
def logout():
    session["uid"] = ""
    session.pop("uid")
    return render_template('login.html')


@app.route('/register')
def register():
    return render_template('register.html')


@app.route('/LoginCheck', methods=['GET', 'POST'])
def LoginCheck():
    phone_number = request.form["phone_number"]
    password = request.form["password"]
    find_user = User.query.filter(User.phone_num == phone_number).first()
    if find_user is None or find_user.verify_password(password) is False:
        return jsonify("0")
    session["uid"] = find_user.user_id
    return jsonify("1")


# !!!注册的时候没检查phone的格式，但是登陆的时候检查了phone的格式
@app.route('/RegisterCheck', methods=['GET', 'POST'])
def RegisterCheck():
    username = request.form["username"]
    phone_number = request.form["phoneNum"]
    password = request.form["password"]

    check_phone = User.query.filter(User.phone_num == phone_number).first()
    if check_phone is not None:
        return jsonify("0")
    password_hash = generate_password_hash(password)
    new_user = User(username=username, phone_num=phone_number, password_hash=password_hash)
    db.session.add(new_user)
    db.session.commit()
    return jsonify("2")


@app.route('/profile')
def profile():
    uid = session.get('uid')
    if uid is None:
        return redirect(url_for('login'))
    user = User.query.filter(User.user_id == uid).first()
    favor_model_set = Favor.query.filter(Favor.user_id == uid)
    favor_model = [{'model': item.model} for item in favor_model_set]
    return render_template('profile.html', user=user, my_model=user.models, favor_model=favor_model)


@app.route('/ModifyProfile', methods=['GET', 'POST'])
def ModifyProfile():
    uid = session.get('uid')
    if uid is None:
        return redirect(url_for('login'))
    user = User.query.filter(User.user_id == uid).first()
    if request.method == 'POST':
        email = request.form["email"]
        check_email = User.query.filter(User.mail == email).first()
        if not email or check_email is None or check_email.user_id == user.user_id:
            sex = request.form["sex"]
            birthday = request.form["birthday"]
            username = request.form["username"]
            user.username = username
            user.mail = email
            user.birthday = birthday
            user.sex = sex
            db.session.commit()
            return jsonify("1")
    return jsonify("0")


@app.route('/ChangeAvatar', methods=['GET', 'POST'])
def ChangeAvatar():
    uid = session.get('uid')
    if uid is None:
        return redirect(url_for('login'))
    user = User.query.filter(User.user_id == uid).first()
    if request.method == 'POST':
        file = request.files['file']
        if file and allow_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join('project', 'static', 'avatar', filename))
            user.avatar_path = filename
            db.session.commit()
            response = json.dumps(filename)
            return response
    return jsonify("0")


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}


def allow_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/download/<filename>', methods=['GET', 'POST'])
def download(filename):
    folder = app.config['DOWNLOAD_FOLDER']
    # 构造供下载文件的完整路径
    path = os.path.join(folder, filename)
    return send_file(path, as_attachment=True)


@app.route('/', methods=['GET', 'POST'])
@app.route('/model_blog', methods=['GET', 'POST'])
def blog():
    uid = session.get('uid')
    model_set = Model.query
    page = request.args.get('page', 1, type=int)
    pagination = model_set.order_by((Model.views.desc())).paginate(
        page, per_page=6,
        error_out=False)
    if uid is None:
        return render_template('model_blog.html', model_set=pagination.items, pagination=pagination)
    user = User.query.filter(User.user_id == uid).first()
    return render_template('model_blog.html', user=user, model_set=pagination.items, pagination=pagination)


@app.route('/model_detail/<model_id>', methods=['GET', 'POST'])
def detail(model_id):
    uid = session.get('uid')
    model = Model.query.filter(Model.model_id == model_id).first()
    comment_set = Comment.query.filter(Comment.model_id == model_id).order_by(Comment.timestamp.desc())
    is_like = 0
    is_favor = 0
    if uid is None:
        return render_template('model_detail.html', model=model, comment_set=comment_set, is_like=is_like,
                               is_favor=is_favor)
    user = User.query.filter(User.user_id == uid).first()
    model.views += 1
    db.session.commit()
    model_like = Like.query.filter(and_(Like.user_id == uid, Like.model_id == model_id)).first()
    model_favor = Favor.query.filter(and_(Favor.user_id == uid, Favor.model_id == model_id)).first()
    if model_like:
        is_like = 1
    if model_favor:
        is_favor = 1
    relevant_model = Model.query.filter(Model.model_tag == model.model_tag).order_by(Model.views.desc())[:3]
    # print(model.comments.count())
    return render_template('model_detail.html', user=user, model=model, is_like=is_like,
                           is_favor=is_favor, relevant_model=relevant_model, comment_set=comment_set)


@app.route('/LikeModel', methods=['GET', 'POST'])
def LikeModel():
    uid = session.get('uid')
    if uid is None:
        return jsonify(1)
    user = User.query.filter(User.user_id == uid).first()
    model_id = request.form["model_id"]
    model = Model.query.filter(Model.model_id == model_id).first()
    a_like = Like(user_id=uid, model_id=model_id, user=user, model=model)
    db.session.add(a_like)
    db.session.commit()
    return jsonify(0)


@app.route('/CancelLikeModel', methods=['GET', 'POST'])
def CancelLikeModel():
    uid = session.get('uid')
    if uid is None:
        return jsonify(1)
    model_id = request.form["model_id"]
    a_like = Like.query.filter(and_(Like.user_id == uid, Like.model_id == model_id)).first()
    db.session.delete(a_like)
    db.session.commit()
    return jsonify(0)


@app.route('/FavorModel', methods=['GET', 'POST'])
def FavorModel():
    uid = session.get('uid')
    if uid is None:
        return jsonify(1)
    user = User.query.filter(User.user_id == uid).first()
    model_id = request.form["model_id"]
    model = Model.query.filter(Model.model_id == model_id).first()
    a_favor = Favor(user_id=uid, model_id=model_id, user=user, model=model)
    db.session.add(a_favor)
    db.session.commit()
    return jsonify(0)


@app.route('/CancelFavorModel', methods=['GET', 'POST'])
def CancelFavorModel():
    uid = session.get('uid')
    if uid is None:
        return jsonify(1)
    model_id = request.form["model_id"]
    a_favor = Favor.query.filter(and_(Favor.user_id == uid, Favor.model_id == model_id)).first()
    db.session.delete(a_favor)
    db.session.commit()
    return jsonify(0)


@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.args.get('query'):
        query = request.args.get('query')
    else:
        query = request.form["query"]
    search_result = "%" + query + "%"
    model_set = Model.query.filter(or_(Model.describe.like(search_result), Model.model_name.like(search_result)))
    result_num = model_set.count()
    page = request.args.get('page', 1, type=int)
    pagination = model_set.order_by((Model.views.desc())).paginate(
        page, per_page=6,
        error_out=False)
    uid = session.get('uid')
    if uid is None:
        return render_template('search.html', result_num=result_num, model_set=pagination.items, query=query,
                               pagination=pagination)
    user = User.query.filter(User.user_id == uid).first()
    return render_template('search.html', result_num=result_num, model_set=pagination.items, query=query,
                           pagination=pagination, user=user)


@app.route('/DeleteModel', methods=['GET', 'POST'])
def DeleteModel():
    uid = session.get('uid')
    if uid is None:
        return jsonify(1)
    model_id = request.form["model_id"]
    a_model = Model.query.filter(Model.model_id == model_id).first()
    if a_model is None:
        return jsonify(1)
    db.session.delete(a_model)
    db.session.commit()
    return jsonify(0)


@app.route('/success')
def success():
    # uid = session.get('uid')
    # if uid is None:
    #     return redirect(url_for('login'))
    # user = User.query.filter(User.user_id == uid).first()
    # return render_template('success_upload.html', user=user)
    return render_template('success_upload.html')


@app.route('/fail')
def fail():
    # uid = session.get('uid')
    # if uid is None:
    #     return redirect(url_for('login'))
    # user = User.query.filter(User.user_id == uid).first()
    # return render_template('fail_upload.html', user=user)
    return render_template('fail_upload.html')