"""网络探针:检测到 GitHub 的三条常用通路(TCP 层连通性)。"""
import socket


def probe(host, port, label):
    try:
        s = socket.socket()
        s.settimeout(6)
        s.connect((host, port))
        s.close()
        print('%-34s 通' % label)
        return True
    except Exception as e:
        print('%-34s 不通(%s)' % (label, type(e).__name__))
        return False


results = [
    probe('github.com', 443, 'github.com:443 (HTTPS 推送)'),
    probe('github.com', 22, 'github.com:22 (SSH 推送)'),
    probe('ssh.github.com', 443, 'ssh.github.com:443 (SSH 走 443 备用)'),
]
print('可用通路数:', sum(results))
