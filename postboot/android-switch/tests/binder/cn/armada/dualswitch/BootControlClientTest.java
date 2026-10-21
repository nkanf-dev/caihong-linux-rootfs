package cn.armada.dualswitch;
import android.os.*;
public final class BootControlClientTest {
    static int assertions;
    static void require(boolean value,String message){assertions++;if(!value)throw new AssertionError(message);}
    interface Operation {void run() throws Exception;}
    static void rejected(Operation op,String message)throws Exception{
        boolean failure=false;try{op.run();}catch(Exception e){failure=true;}require(failure,message);
    }
    static final class FakeBinder implements IBinder {
        String descriptor=BootControlClient.DESCRIPTOR, hash=TargetConfig.AIDL_HASH;
        int version=TargetConfig.AIDL_VERSION, badTransaction=-1, writes;
        boolean alive=true, unsupported, exception, extra, empty, missingValue;
        public boolean isBinderAlive(){return alive;}
        public String getInterfaceDescriptor(){return descriptor;}
        public boolean transact(int code,Parcel data,Parcel reply,int flags)throws Exception{
            require(flags==0,"synchronous transact");data.enforceToken(BootControlClient.DESCRIPTOR);
            boolean bad=code==badTransaction;
            if(bad && unsupported)return false;
            if(bad && empty)return true;
            reply.writeInt(bad && exception ? -1 : 0);
            if(bad && missingValue)return true;
            if(code==BootControlClient.GET_HASH)reply.writeString(hash);
            else if(code==BootControlClient.GET_VERSION)reply.writeInt(version);
            else if(code==BootControlClient.GET_ACTIVE)reply.writeInt(0);
            else if(code==BootControlClient.GET_CURRENT)reply.writeInt(0);
            else if(code==BootControlClient.GET_SLOTS)reply.writeInt(2);
            else if(code==BootControlClient.GET_MERGE)reply.writeInt(0);
            else if(code==BootControlClient.GET_SUFFIX)reply.writeString(data.readInt()==0?"_a":"_b");
            else if(code==BootControlClient.IS_BOOTABLE){require(data.readInt()==1,"slot argument");reply.writeInt(1);}
            else if(code==BootControlClient.SET_ACTIVE){require(data.readInt()==1,"target argument");writes++;}
            else throw new AssertionError("unexpected transaction "+code);
            require(data.dataAvail()==0,"no excess request arguments");
            if(bad && extra)reply.writeInt(42);
            return true;
        }
    }
    static FakeBinder install(){FakeBinder f=new FakeBinder();ServiceManager.service=f;return f;}
    public static void main(String[] args)throws Exception{
        FakeBinder f=install();BootControlClient c=new BootControlClient();
        require(c.version==1 && c.hash.equals(TargetConfig.AIDL_HASH),"version and hash accepted");
        require(c.integer(BootControlClient.GET_CURRENT,null)==0,"current slot parsed");
        require(c.integer(BootControlClient.GET_ACTIVE,null)==0,"next active slot parsed");
        require(c.integer(BootControlClient.GET_SLOTS,null)==2,"slot count parsed");
        require(c.integer(BootControlClient.GET_MERGE,null)==0,"merge parsed");
        require(c.string(BootControlClient.GET_SUFFIX,1).equals("_b"),"suffix parsed");
        require(c.bootable(1),"boolean parsed");c.setActive(1);require(f.writes==1,"target write exactly once");
        ServiceManager.service=null;rejected(()->new BootControlClient(),"missing service rejected");
        f=install();f.alive=false;rejected(()->new BootControlClient(),"dead binder rejected");
        f=install();f.descriptor="other";rejected(()->new BootControlClient(),"wrong descriptor rejected");
        f=install();f.version=2;rejected(()->new BootControlClient(),"unreviewed version rejected");
        f=install();f.hash="notfrozen";rejected(()->new BootControlClient(),"unreviewed hash rejected");
        for(String failure:new String[]{"unsupported","exception","extra","empty","missingValue"}){
            f=install();c=new BootControlClient();f.badTransaction=BootControlClient.GET_ACTIVE;
            if(failure.equals("unsupported"))f.unsupported=true;
            if(failure.equals("exception"))f.exception=true;
            if(failure.equals("extra"))f.extra=true;
            if(failure.equals("empty"))f.empty=true;
            if(failure.equals("missingValue"))f.missingValue=true;
            final BootControlClient client=c;
            rejected(()->client.integer(BootControlClient.GET_ACTIVE,null),failure+" reply rejected");
        }
        f=install();c=new BootControlClient();f.badTransaction=BootControlClient.SET_ACTIVE;f.extra=true;
        final BootControlClient writeClient=c;rejected(()->writeClient.setActive(1),"extra void response rejected");
        require(Parcel.obtained==Parcel.recycled,"all parcels recycled after success and failures");
        System.out.println("BootControlClientTest: PASS ("+assertions+" assertions; test-double Parcel/Binder)");
    }
}
