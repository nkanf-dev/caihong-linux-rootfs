package cn.armada.dualswitch;

import java.io.File;

final class BlockIdentity {
    private BlockIdentity() {}
    static long major(long dev) { return ((dev >>> 8) & 0xfffL) | ((dev >>> 32) & 0xfffff000L); }
    static long minor(long dev) { return (dev & 0xffL) | ((dev >>> 12) & 0xffffff00L); }
    static String partname(String uevent) throws Exception {
        String part = null;
        for (String line : uevent.split("\n")) {
            if (line.startsWith("PARTNAME=")) {
                if (part != null) throw new Exception("分区名称重复");
                part = line.substring(9);
            }
        }
        if (part == null) throw new Exception("缺少分区名称");
        return part;
    }
    static void requireBootB(String canonicalPath,String uevent,String sysDev,long rdev) throws Exception {
        if (!new File(canonicalPath).isAbsolute() || !canonicalPath.startsWith("/dev/block/")
                || canonicalPath.contains("/../") || canonicalPath.contains("/by-name/"))
            throw new Exception("boot_b 真实设备路径无效");
        if (!"boot_b".equals(partname(uevent))) throw new Exception("目标分区名称不是 boot_b");
        String expected = major(rdev) + ":" + minor(rdev);
        if (!expected.equals(sysDev.trim())) throw new Exception("boot_b 设备号与 sysfs 不匹配");
    }
}
