"""用 Windows 所选项目的公开配置构建可登录的 Android 调试包。"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desk_companion.accounts.account_store import AccountStore
from desk_companion.accounts.personalization_cloud import CloudConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-dir', type=Path, default=ROOT / 'android', help='Android 项目或隔离验收副本')
    args = parser.parse_args()
    if os.environ.get('TEBB_CLOUD_URL') or os.environ.get('TEBB_CLOUD_PUBLISHABLE_KEY'):
        config = CloudConfig.from_env(os.environ)
    else:
        public = AccountStore(ROOT).read()['config']
        if not public:
            raise SystemExit('请在 Windows 配置账号服务，或提供 TEBB_CLOUD_URL 和 TEBB_CLOUD_PUBLISHABLE_KEY。')
        config = CloudConfig(**public)
    if not config.url.startswith('https://') or not config.publishable_key.startswith('sb_publishable_'):
        raise SystemExit('手机登录构建需要 HTTPS 项目地址和 publishable key。')
    android = args.android_dir.resolve()
    env = dict(os.environ, TEBB_CLOUD_URL=config.url, TEBB_CLOUD_PUBLISHABLE_KEY=config.publishable_key)
    subprocess.run([str(android / ('gradlew.bat' if os.name == 'nt' else 'gradlew')), ':app:assembleDebug'],
                   cwd=android, env=env, check=True)
    apk = android / 'app/build/outputs/apk/debug/app-debug.apk'
    missing = {config.url.encode(), config.publishable_key.encode()}
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if name.endswith('.dex') and missing:
                content = archive.read(name)
                missing = {value for value in missing if value not in content}
    if missing:
        raise SystemExit('APK 未包含所选项目的公开配置。')
    print(f'已核对 APK 内的账号项目配置：{apk}')


if __name__ == '__main__':
    main()
