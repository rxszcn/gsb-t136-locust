"""按用户类的 ramp 速率面板（只写现象，不写修法）。

跑法（副本内）：
    cd /tmp/b136-xxx && .venv/bin/python spawn-rate-panel.py
locust 用 venv 里的 editable 装法，首行打印被测 locust 的 __file__ 坐实测的是副本里的代码。
"""

import inspect
import io
import time
from contextlib import redirect_stderr

import gevent
import locust
from locust import User, constant, task
from locust.dispatch import UsersDispatcher
from locust.env import Environment
from locust.shape import LoadTestShape

print("TARGET locust.__file__ =", locust.__file__, "| version =", locust.__version__)

results = []
RATE = {"BotA": 1, "BotB": 5}


class BotA(User):
    weight = 1
    wait_time = constant(0)

    @task
    def t(self):
        gevent.sleep(0.05)


class BotB(User):
    weight = 1
    wait_time = constant(0)

    @task
    def t(self):
        gevent.sleep(0.05)


def cell(label, fn, want):
    try:
        got = fn()
    except BaseException as exc:  # 起点里走不通的写法也要让整块面板跑完
        got = "RAISED:" + type(exc).__name__ + ":" + str(exc)[:70]
    ok = got == want
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label + " | got=" + repr(got) + " want=" + repr(want))
    return got


def new_runner(**kwargs):
    env = Environment(user_classes=[BotA, BotB], **kwargs)
    return env.create_local_runner()


def counts(r):
    return dict(r.user_classes_count)


# --- F1 / F2 / F3：同一个本地 ramp 上的三个读数 ---
box = {"err": None}
r = new_runner()
try:
    r.start(6, dict(RATE))
except BaseException as exc:
    box["err"] = type(exc).__name__ + ":" + str(exc)[:60]
gevent.sleep(1.2)
mid = counts(r)
cell("F1 runner.start(6, {类名:速率}) 调用方拿不到异常", lambda: box["err"], None)
cell("F2 t=1.2s 时两类各自的实例数按各自速率", lambda: (mid.get("BotA", 0) <= 2, mid.get("BotB", 0) >= 3), (True, True))
print("     F2 counts@1.2s=%s state=%s" % (mid, r.state))
gevent.sleep(2.5)
fin = counts(r)
cell("F3 ramp 收尾：总数到 6 且按各自速率定构成", lambda: (sum(fin.values()), fin.get("BotA"), fin.get("BotB"), r.state), (6, 1, 5, "running"))
print("     F3 counts@3.7s=%s state=%s target=%s" % (fin, r.state, r.target_user_count))
r.quit()

# --- F4：直接把按类速率喂给 UsersDispatcher ---
_f4_spent = [0.0]


def f4():
    from locust.runners import WorkerNode

    nodes = [WorkerNode(id="w1"), WorkerNode(id="w2")]
    d = UsersDispatcher(nodes, [BotA, BotB])
    t0 = time.perf_counter()
    d.new_dispatch(target_user_count=6, spawn_rate=dict(RATE))
    seen = None
    for users_on_workers in d:
        seen = users_on_workers
    spent = time.perf_counter() - t0
    _f4_spent[0] = spent
    per_class = {}
    for node_counts in (seen or {}).values():
        for name, n in node_counts.items():
            per_class[name] = per_class.get(name, 0) + n
    return per_class, 0.6 <= spent <= 2.5


cell("F4 UsersDispatcher.new_dispatch 收到 {类名:速率} 后按各自节律吐完 6 个", f4, ({"BotA": 1, "BotB": 5}, True))
print("     F4a 吐完 6 个用了 %s 秒" % round(_f4_spent[0], 2))
print("     F4b new_dispatch 签名: %s" % (inspect.signature(UsersDispatcher.new_dispatch),))

# --- F5：命令行写法 ---
def f5():
    from locust.argument_parser import get_parser

    err = io.StringIO()
    try:
        with redirect_stderr(err):
            opts = get_parser().parse_args(
                ["-f", __file__, "--headless", "-u", "6", "-t", "1s", "-r", "BotA=1,BotB=5"]
            )
    except SystemExit as exc:
        return "rc=%s %s" % (exc.code, err.getvalue().strip().splitlines()[-1][:70])
    return opts.spawn_rate


cell("F5 命令行 -r BotA=1,BotB=5 解析出来的值", f5, {"BotA": 1.0, "BotB": 5.0})

# --- F6：shape 的 tick 契约能不能声明按类速率 ---
def f6():
    ann = LoadTestShape.tick.__annotations__.get("return")
    text = ann if isinstance(ann, str) else str(ann)
    return ("dict" in text.lower(), text)


cell("F6 tick 的返回注解里出现了按类速率的形状", lambda: f6()[0], True)
print("     F6b annotation=%s" % f6()[1])


# --- F7：shape 驱动的按类 ramp ---
class PerClassShape(LoadTestShape):
    def tick(self):
        if self.get_run_time() < 6.0:
            return 6, dict(RATE)
        return None


def f7():
    r2 = new_runner(shape_class=PerClassShape())
    r2.start_shape()
    gevent.sleep(1.2)
    mid2 = counts(r2)
    gevent.sleep(2.0)
    fin2 = counts(r2)
    r2.quit()
    paced = mid2.get("BotA", 0) <= 2 and mid2.get("BotB", 0) >= 3
    return paced, sum(fin2.values()), fin2.get("BotA", 0), fin2.get("BotB", 0)


cell("F7 shape 的 tick 给 {类名:速率} 时本地按类 ramp 到 6", f7, (True, 6, 1, 5))

# --- F8：标量写法的既有节律不许变 ---
def f8():
    r3 = new_runner()
    r3.start(4, 2)
    gevent.sleep(0.4)
    early = sum(counts(r3).values())
    gevent.sleep(1.4)
    late = sum(counts(r3).values())
    st = r3.state
    r3.quit()
    return (early, late, st)


cell("F8 标量 start(4, 2)：0.4s 起 2 个、1.8s 起满 4 个", f8, (2, 4, "running"))

print("PANEL %d/%d" % (sum(results), len(results)))
