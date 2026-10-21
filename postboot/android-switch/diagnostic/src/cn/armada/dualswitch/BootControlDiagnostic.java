package cn.armada.dualswitch;

import android.os.SystemClock;
import org.json.JSONObject;
import java.util.Timer;
import java.util.TimerTask;

/** No process launch or reboot command exists in this diagnostic entry point. */
public final class BootControlDiagnostic {
 private static void emit(JSONObject j){System.out.println(j.toString());System.out.flush();}
 public static void main(String[] args){
  final long started=SystemClock.elapsedRealtime();
  final long deadline=started+60_000L;
  Timer timer=new Timer(true);
  timer.schedule(new TimerTask(){public void run(){
   System.out.println("{\"protocol\":1,\"event\":\"timeout\",\"error\":\"诊断超时，请重新读取当前槽和下次启动槽\",\"rebootRequested\":false}");
   System.out.flush();System.exit(124);
  }},120_000L);
  int exit=0;
  try{
   if(args.length!=1 || (!"status".equals(args[0]) && !"select-b-no-reboot".equals(args[0])))
    throw new Exception("命令仅支持 status 或 select-b-no-reboot");
   JSONObject out=new JSONObject();out.put("protocol",1);out.put("command",args[0]);
   out.put("startedElapsedMs",started);out.put("deadlineElapsedMs",deadline);out.put("rebootRequested",false);
   if("status".equals(args[0])){
    Policy.Status s=DiagnosticState.inspect();out.put("before",DiagnosticState.json(s));
    out.put("after",JSONObject.NULL);out.put("setActiveAttempted",false);out.put("setActiveCompleted",false);
    if(!s.error.isEmpty())exit=1;
   }else{
    DiagnosticCoordinator.Result r=DiagnosticCoordinator.select(new DiagnosticCoordinator.Backend(){
     public void checkDeadline()throws Exception{SwitchDeadline.check(SystemClock.elapsedRealtime(),deadline);}
     public Policy.Status inspect(){return DiagnosticState.inspect();}
     public void refreshHal(Policy.Status s)throws Exception{DiagnosticState.readHal(s);}
     public void setActiveB()throws Exception{new BootControlClient().setActive(1);}
     public Policy.Status readAfter()throws Exception{Policy.Status s=new Policy.Status();DiagnosticState.readHal(s);return s;}
    });
    out.put("before",r.before==null?JSONObject.NULL:DiagnosticState.json(r.before));
    out.put("after",r.after==null?JSONObject.NULL:DiagnosticState.halJson(r.after));
    out.put("setActiveAttempted",r.attempted);out.put("setActiveCompleted",r.completed);
    out.put("setActiveReturnType","void");out.put("setActiveReturnValue",JSONObject.NULL);
    out.put("error",r.error);out.put("afterReadError",r.afterError);
    out.put("selectionReadbackMatches",r.after!=null && r.after.active==1 && r.after.current==0 && r.after.bootableB);
    if(!r.error.isEmpty() || !r.afterError.isEmpty() || r.after==null || r.after.active!=1)exit=1;
   }
   out.put("finishedElapsedMs",SystemClock.elapsedRealtime());emit(out);
  }catch(Throwable e){
   try{JSONObject out=new JSONObject();out.put("protocol",1);out.put("error",DiagnosticState.brief(e));out.put("rebootRequested",false);emit(out);}
   catch(Exception ignored){System.err.println(DiagnosticState.brief(e));}exit=1;
  }finally{timer.cancel();}
  System.exit(exit);
 }
}
