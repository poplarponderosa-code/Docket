import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docket.geometry import snap   # noqa: E402

SCREEN = (0, 0, 1920, 1040)


def test_snaps_side_by_side_and_lines_up():
    other = (500, 300, 300, 42)                        # a pill at x 500..800
    assert snap(806, 305, 250, 42, [other], SCREEN) == (800, 300)     # right side, tops lined up
    assert snap(245, 296, 250, 42, [other], SCREEN) == (250, 300)     # left side: 250 + 250 = 500


def test_stacks_and_aligns_left_edges():
    other = (500, 300, 300, 42)
    assert snap(507, 348, 300, 42, [other], SCREEN) == (500, 342)     # just below, left edges lined up


def test_screen_edges_and_far_away():
    assert snap(7, 1000, 300, 42, [], SCREEN) == (0, 998)              # left and bottom screen edges
    assert snap(900, 600, 300, 42, [(100, 100, 200, 42)], SCREEN) == (900, 600)   # nothing near


def test_touching_group():
    from docket.geometry import touching_group
    rects = [(0, 0, 100, 40), (100, 0, 100, 40), (200, 41, 50, 40), (500, 500, 10, 10)]
    assert touching_group(0, rects) == [0, 1, 2]       # a chain counts; 1px gap allowed
    assert touching_group(3, rects) == [3]
