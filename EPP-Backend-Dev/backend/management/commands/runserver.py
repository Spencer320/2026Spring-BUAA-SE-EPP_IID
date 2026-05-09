from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticfilesRunserverCommand,
)


class Command(StaticfilesRunserverCommand):
    """开发服务器默认监听所有网卡，便于局域网/容器访问。"""

    default_addr = "0.0.0.0"
