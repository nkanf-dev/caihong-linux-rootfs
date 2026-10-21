package cn.armada.dualswitch;
public final class SwitchDeadlineTest {
    static int assertions;
    static void reject(long now,long deadline)throws Exception{
        boolean rejected=false;try{SwitchDeadline.check(now,deadline);}catch(Exception e){rejected=true;}
        assertions++;if(!rejected)throw new AssertionError("unsafe deadline accepted");
    }
    public static void main(String[] args)throws Exception{
        SwitchDeadline.check(100,60100);assertions++;
        SwitchDeadline.check(100,101);assertions++;
        reject(100,100);reject(100,99);reject(100,60101);reject(-1,100);
        System.out.println("SwitchDeadlineTest: PASS ("+assertions+" assertions)");
    }
}
