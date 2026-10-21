package android.os;
public interface IBinder {
 int FIRST_CALL_TRANSACTION=1;
 boolean isBinderAlive(); String getInterfaceDescriptor();
 boolean transact(int code,Parcel data,Parcel reply,int flags) throws Exception;
}
