"""终端自适应渲染的纯函数测试:缩放选择、居中定位、超宽截断、防折行。

运行:python3 tests/test_display.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chip8.emu import clip, dwidth, fit, paint  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def fit_picks_scale():
    assert fit(64, 18, 2) == 1          # 刚好装下半块(16 行屏 + 2 行说明)
    assert fit(64, 17, 2) == 0          # 少一行:提示,不硬画
    assert fit(63, 40, 2) == 0          # 少一列:提示
    assert fit(80, 40, 2) == 1          # 常规终端
    assert fit(128, 34, 2) == 2         # 刚好装下 2x
    assert fit(128, 33, 2) == 1         # 高度差一行,退回半块
    assert fit(200, 60, 2) == 2


@test
def dwidth_and_clip():
    assert dwidth('ab') == 2
    assert dwidth('键位:x') == 6        # 全角 2+2,半角 1+1
    assert clip('abcde', 3) == 'abc'
    assert clip('键位:1234', 5) == '键位:'  # 全角按 2 计,装不下整字宁缺
    assert clip('中文', 10) == '中文'


@test
def paint_centers_and_positions():
    text, view = paint(80, 21, ['█' * 64], ['hint'], None)
    assert view == (80, 21, 1)
    assert '\x1b[2J' in text            # 首帧整屏清一次
    assert '\x1b[10;9H' in text         # top=(21-2)/2=9, left=(80-64)/2=8
    assert '\n' not in text             # 全程不靠换行排版,防 raw 模式楼梯
    text2, view2 = paint(80, 21, ['█' * 64], ['hint'], view)
    assert '\x1b[2J' not in text2       # 视图没变:原地覆盖,不重复清屏
    text3, _ = paint(100, 21, ['█' * 64], ['hint'], view2)
    assert '\x1b[2J' in text3           # 窗口变了:先清一次再画
    assert '\x1b[10;19H' in text3       # left=(100-64)/2=18


@test
def paint_width_follows_widest_line():
    wide = '键' * 33                    # 显示宽 66,比 64 列的屏幕还宽
    text, _ = paint(80, 21, ['█' * 64], [wide], None)
    assert '\x1b[10;8H' in text         # left=(80-66)/2=7,按最宽行居中
    assert clip(wide, 80 - 7) == wide   # 截断阈值保证不折行


@test
def paint_too_small_hint():
    text, view = paint(40, 10, [], ['窗口太小'], None, '\x1b[1;31m')
    assert view == (40, 10, 0)
    assert '\x1b[1;31m' in text and '窗口太小' in text
    assert '\x1b[5;17H' in text         # 单行提示也居中:top=4, left=16


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
