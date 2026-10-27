"""下载并安装 zig 到 ~/computer-lab/tools/zig(阶段3交叉编译 C 用)。

只依赖 Python 标准库;网络不通时以非零码退出,由调用方降级到阶段3b。
"""
import json
import os
import shutil
import tarfile
import urllib.request

TOOLS = '/home/dazi9/computer-lab/tools'
URL = 'https://ziglang.org/download/index.json'
FINAL = os.path.join(TOOLS, 'zig')
UA = {'User-Agent': 'rvlab/1.0'}


def fetch(url, dest, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=timeout) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f, 1 << 20)


def main():
    if os.path.exists(os.path.join(FINAL, 'zig')):
        print('zig 已安装:', FINAL)
        return
    os.makedirs(TOOLS, exist_ok=True)
    print('获取版本索引 ...')
    with urllib.request.urlopen(urllib.request.Request(URL, headers=UA),
                                timeout=60) as r:
        index = json.load(r)
    version = next(v for v in index if v != 'master')      # 首个稳定版
    info = index[version]['x86_64-linux']
    size = info.get('size') or 0
    print('选定 zig %s(size=%s)' % (version, size))
    raw = os.path.join(TOOLS, 'zig.tar.xz')
    fetch(info['tarball'], raw)
    print('下载完成,解压 ...')
    with tarfile.open(raw) as t:
        t.extractall(TOOLS)
    os.remove(raw)
    cand = [d for d in os.listdir(TOOLS)
            if d.startswith('zig-') and os.path.isdir(os.path.join(TOOLS, d))]
    if not cand:
        raise RuntimeError('解压后没找到 zig 目录')
    if os.path.exists(FINAL):
        shutil.rmtree(FINAL)
    os.rename(os.path.join(TOOLS, cand[0]), FINAL)
    print('安装到:', FINAL)


if __name__ == '__main__':
    main()
