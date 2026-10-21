package cn.armada.dualswitch;

import android.os.IBinder;
import android.os.Parcel;

/** Transaction constants are checked against SDK-generated frozen AOSP AIDL v1 at build time. */
final class BootControlClient {
    static final String DESCRIPTOR = "android.hardware.boot.IBootControl";
    static final int GET_ACTIVE = IBinder.FIRST_CALL_TRANSACTION + 0;
    static final int GET_CURRENT = IBinder.FIRST_CALL_TRANSACTION + 1;
    static final int GET_SLOTS = IBinder.FIRST_CALL_TRANSACTION + 2;
    static final int GET_MERGE = IBinder.FIRST_CALL_TRANSACTION + 3;
    static final int GET_SUFFIX = IBinder.FIRST_CALL_TRANSACTION + 4;
    static final int IS_BOOTABLE = IBinder.FIRST_CALL_TRANSACTION + 5;
    static final int SET_ACTIVE = IBinder.FIRST_CALL_TRANSACTION + 8;
    static final int GET_VERSION = IBinder.FIRST_CALL_TRANSACTION + 16777214;
    static final int GET_HASH = IBinder.FIRST_CALL_TRANSACTION + 16777213;
    private final IBinder binder;
    final int version;
    final String hash;
    BootControlClient() throws Exception {
        binder = (IBinder) Class.forName("android.os.ServiceManager")
            .getMethod("getService", String.class).invoke(null, DESCRIPTOR + "/default");
        if (binder == null || !binder.isBinderAlive()) throw new Exception("找不到启动 HAL AIDL 服务");
        if (!DESCRIPTOR.equals(binder.getInterfaceDescriptor()))
            throw new Exception("启动 HAL descriptor 不匹配");
        version = integer(GET_VERSION, null);
        hash = string(GET_HASH, null);
        if (version != TargetConfig.AIDL_VERSION || !TargetConfig.AIDL_HASH.equals(hash))
            throw new Exception("启动 HAL 版本或接口哈希不匹配：" + version + " / " + hash);
    }
    private interface Read<T> { T read(Parcel p); }
    private <T> T call(int transaction, Integer arg, Read<T> read) throws Exception {
        Parcel data = Parcel.obtain();
        Parcel reply = Parcel.obtain();
        try {
            data.writeInterfaceToken(DESCRIPTOR);
            if (arg != null) data.writeInt(arg);
            if (!binder.transact(transaction, data, reply, 0))
                throw new Exception("启动 HAL 不支持 transaction " + transaction);
            if (reply.dataAvail() < 4) throw new Exception("启动 HAL 返回缺少异常状态");
            reply.readException();
            T value = read.read(reply);
            if (reply.dataAvail() != 0) throw new Exception("启动 HAL 返回了多余数据");
            return value;
        } finally { reply.recycle(); data.recycle(); }
    }
    int integer(int transaction, Integer arg) throws Exception {
        return call(transaction, arg, p -> {
            if (p.dataAvail() != 4) throw new IllegalStateException("启动 HAL 整数返回长度无效");
            return p.readInt();
        });
    }
    String string(int transaction, Integer arg) throws Exception {
        String result = call(transaction, arg, p -> {
            if (p.dataAvail() < 4) throw new IllegalStateException("启动 HAL 字符串返回长度无效");
            return p.readString();
        });
        if (result == null) throw new Exception("启动 HAL 返回空字符串");
        return result;
    }
    boolean bootable(int slot) throws Exception {
        int value = integer(IS_BOOTABLE, slot);
        if (value != 0 && value != 1) throw new Exception("启动 HAL 布尔值无效");
        return value == 1;
    }
    void setActive(int slot) throws Exception {
        call(SET_ACTIVE, slot, p -> null);
    }
}
