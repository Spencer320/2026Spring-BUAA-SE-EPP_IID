from django.core.management.base import BaseCommand
from django.core.cache import caches


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            "-n",
            "--name",
            action="store",
            dest="name",
            default="default",
            help="clean django cache",
        )

    def handle(self, *args, **options):
        try:
            if options["name"]:
                cache = caches[options["name"]]
                cache.clear()
            self.stdout.write(self.style.SUCCESS("缓存清理成功"))
        except Exception as ex:
            self.stdout.write(self.style.ERROR("命令执行出错"))
