package cn.armada.dualswitch;

final class SwitchDeadline {
    private SwitchDeadline() {}
    static void check(long now,long deadline) throws Exception {
        if (now < 0 || deadline <= now || deadline-now > 60_000L)
            throw new Exception("切换确认已过期，请重新检查并确认");
    }
}
