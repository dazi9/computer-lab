"""终端自适应渲染的纯函数测试:framebuffer 两档帧形、缩放选择、居中定位。

运行:python3 tests/test_display.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rv.emu import clip, dwidth, fit, half_block, paint, wide_frame  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def frames_from_fb():
    fb = bytearray(256)
    fb[0] = 0x80            # 只亮 (0,0):上半块 ▀
    hb = half_block(bytes(fb))
    assert len(hb) == 16 and all(len(line) == 64 for line in hb)
    assert hb[0][0] == '▀' and hb[0][1:] == ' ' * 63
    assert wide_frame(bytes(fb))[0][:2] == '██'
    fb[8] = 0x80            # (1,0) 也亮:上下都亮 → 全块 █
    assert half_block(bytes(fb))[0][0] == '█'
    wf = wide_frame(bytes(fb))
    assert len(wf) == 32 and all(len(line) == 128 for line in wf)
    assert wf[0][:2] == '██' and wf[0][2:] == ' ' * 126
    fb[0] = 0xC0            # (0,1) 也亮:2x 模式横向相邻 → 4 连块
    assert wide_frame(bytes(fb))[0][:4] == '████'
    only_bot = bytearray(fb)
    only_bot[0] = 0x00      # 只亮 (1,0):下半块 ▄
    assert half_block(bytes(only_bot))[0][0] == '▄'


@test
def fit_picks_scale():
    assert fit(64, 18, 2) == 1          # 刚好装下半块
    assert fit(64, 17, 2) == 0          # 少一行:提示,不硬画
    assert fit(80, 40, 2) == 1          # 常规终端
    assert fit(128, 34, 2) == 2         # 刚好装下 2x
    assert fit(128, 33, 2) == 1         # 高度差一行,退回半块
    assert fit(200, 60, 2) == 2


@test
def dwidth_and_clip():
    assert dwidth('键位:x') == 6
    assert clip('键位:1234', 5) == '键位:'  # 全角按 2 计,装不下整字宁缺


@test
def paint_centers_and_positions():
    text, view = paint(80, 21, ['█' * 64], ['tail', 'stat'], None)
    assert view == (80, 21, 1)
    assert '\x1b[2J' in text
    assert '\x1b[10;9H' in text         # top=(21-3)/2=9, left=(80-64)/2=8
    assert '\n' not in text             # 全程不靠换行排版,防 raw 模式楼梯
    text2, _ = paint(80, 21, ['█' * 64], ['tail', 'stat'], view)
    assert '\x1b[2J' not in text2       # 视图没变:原地覆盖
    text3, _ = paint(40, 10, [], ['窗口太小'], None, '\x1b[1;31m')
    assert '\x1b[5;17H' in text3        # 单行提示居中:top=4, left=16


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print('PASS', fn.__name__)
        except AssertionError as e:
            failed += 1
            print('FAIL', fn.__name__, '->', e)
    print('---')
    print('%d/%d 组测试通过' % (len(TESTS) - failed, len(TESTS)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
