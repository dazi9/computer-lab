"""下载并安装 zig 到仓库的 tools/zig(阶段3交叉编译 C 用)。

只依赖 Python 标准库;网络不通时以非零码退出,由调用方降级到阶段3b。

环境变量:
    ZIG_VERSION  指定版本,默认 0.17.0(与项目验证过的版本一致)
    ZIG_TOOLS    指定安装目录,默认 <仓库根>/tools
    ZIG_MIRROR   下载镜像前缀(需镜像 ziglang.org/download 的目录结构)
"""
import json
import os
import platform
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.environ.get('ZIG_TOOLS') or os.path.join(ROOT, 'tools')
FINAL = os.path.join(TOOLS, 'zig')
VERSION = os.environ.get('ZIG_VERSION') or '0.17.0'
MIRROR = (os.environ.get('ZIG_MIRROR') or '').rstrip('/')
URL = 'https://ziglang.org/download/index.json'
UA = {'User-Agent': 'computer-lab/1.0'}


def platform_key():
    """本机平台 → zig 下载索引的键,如 x86_64-linux / aarch64-macos。"""
    machine = platform.machine().lower()
    machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(machine, machine)
    system = platform.system().lower()
    system = {'darwin': 'macos'}.get(system, system)
    return '%s-%s' % (machine, system)


def fetch(url, dest, timeout=30, retries=5):
    """带断点续传的下载:网络抖动时从已下载的字节继续,最多重试 5 次。"""
    for attempt in range(1, retries + 1):
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        headers = dict(UA)
        if have:
            headers['Range'] = 'bytes=%d-' % have
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if have and r.status != 206:        # 服务器不认 Range,只能重下
                    have = 0
                total = have + int(r.headers.get('Content-Length') or 0)
                with open(dest, 'ab' if have else 'wb') as f:
                    while True:
                        buf = r.read(1 << 20)
                        if not buf:
                            break
                        f.write(buf)
                        have += len(buf)
                        if total and sys.stdout.isatty():
                            print('\r  %5.1f%%  %.1f/%.1f MB'
                                  % (100.0 * have / total, have / 2**20, total / 2**20),
                                  end='', flush=True)
            if total and os.path.getsize(dest) != total:
                raise IOError('下载不完整: %d/%d 字节' % (os.path.getsize(dest), total))
            if sys.stdout.isatty():
                print()
            return
        except urllib.error.HTTPError as e:
            if e.code == 416:                      # 已经下完(续传越界)
                if sys.stdout.isatty():
                    print()
                return
            print('\n下载中断(%s),第 %d/%d 次重试 ...' % (e, attempt, retries))
            if attempt == retries:
                raise
        except Exception as e:
            print('\n下载中断(%s),第 %d/%d 次重试 ...' % (e, attempt, retries))
            if attempt == retries:
                raise


def installed():
    return any(os.path.exists(os.path.join(FINAL, n)) for n in ('zig', 'zig.exe'))


def extract(archive, dest):
    if archive.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
        return
    with tarfile.open(archive) as t:
        try:
            t.extractall(dest, filter='data')      # Python 3.12+
        except TypeError:
            t.extractall(dest)


def main():
    if installed():
        print('zig 已安装:', FINAL)
        return
    os.makedirs(TOOLS, exist_ok=True)
    print('获取版本索引 ...')
    with urllib.request.urlopen(urllib.request.Request(URL, headers=UA),
                                timeout=60) as r:
        index = json.load(r)

    if VERSION not in index:
        raise SystemExit('索引里没有 zig %s,可用版本: %s'
                         % (VERSION, ', '.join(v for v in index if v != 'master')))
    key = platform_key()
    info = index[VERSION].get(key)
    if not info or 'tarball' not in info:
        avail = [k for k in index[VERSION] if '-' in k]
        raise SystemExit('zig %s 没有 %s 的预编译包。\n可用: %s\n'
                         '也可以手动安装后设置 ZIG=/path/to/zig'
                         % (VERSION, key, ', '.join(avail)))

    size = info.get('size') or 0
    print('选定 zig %s / %s(size=%s)' % (VERSION, key, size))
    archive = info['tarball']
    if MIRROR:                                   # 只换下载前缀,包名仍取自官方索引
        archive = '%s/%s/%s' % (MIRROR, VERSION, os.path.basename(archive))
    raw = os.path.join(TOOLS, 'zig' + ('.zip' if archive.endswith('.zip') else '.tar.xz'))
    if os.path.exists(raw):
        print('检测到未完成的下载,尝试续传 ...')
    fetch(archive, raw)
    print('下载完成,解压 ...')
    extract(raw, TOOLS)
    os.remove(raw)

    cand = [d for d in os.listdir(TOOLS)
            if d.startswith('zig-') and os.path.isdir(os.path.join(TOOLS, d))]
    if not cand:
        raise SystemExit('解压后没找到 zig 目录(下载包结构可能变了)')
    cand.sort(key=lambda d: os.path.getmtime(os.path.join(TOOLS, d)), reverse=True)
    if os.path.exists(FINAL):
        shutil.rmtree(FINAL)
    os.rename(os.path.join(TOOLS, cand[0]), FINAL)
    print('安装到:', FINAL)


if __name__ == '__main__':
    main()
