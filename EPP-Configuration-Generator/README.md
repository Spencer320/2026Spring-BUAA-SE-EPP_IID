# EPP 文献调研助手配置助手

使用这个脚本，可以帮助你快速填写、保存、加载 EPP 文献调研助手配置。

推荐目录结构：

```
`- 项目根目录
 |
 `-  EPP-Frontend-Dev                   前端开发目录
 |
 `-  EPP-Frontend-Manager-Dev           前端（管理员）开发目录
 |
 `-  EPP-Backend-Dev                    后端开发目录
 |
 `-  EPP-Configuration                  配置中心（可自动生成）
 |
 `-  EPP-Configuration-Generator        配置助手
```

在配置助手中，使用如下命令安装依赖：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

而后启动配置助手：

```bash
python generator.py
```

在其中可进行配置的填写，并进行保存、加载、导出、预览。

## 配置的保存与加载

此处，保存与加载的文件仅配置助手可读取，为单文件形式，方便快速部署与恢复。

配置助手并不能从已经导出的配置中再次读取信息，因此请使用这种手段进行保存！

## 配置的导出与预览

预览可以查看生成的配置内容，但不会实际写入任何文件。

导出时需要选择**项目根目录**，也即上文中“目录结构”中的根目录。导出会创建 `EPP-Configuration` 文件夹，并在其中写入配置。

## 配置的装配

一般来说，通过 `bash` 直接运行导出的 `EPP-Configuration/link.sh` 即可自动进行符号链接。
