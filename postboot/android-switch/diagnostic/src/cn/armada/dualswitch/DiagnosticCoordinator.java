package cn.armada.dualswitch;

final class DiagnosticCoordinator {
 interface Backend {
  void checkDeadline()throws Exception;
  Policy.Status inspect()throws Exception;
  void refreshHal(Policy.Status s)throws Exception;
  void setActiveB()throws Exception;
  Policy.Status readAfter()throws Exception;
 }
 static final class Result {
  Policy.Status before,after;
  boolean attempted,completed;
  String error="",afterError="";
 }
 static Result select(Backend b){
  Result r=new Result();
  try{
   b.checkDeadline();r.before=b.inspect();
   if(!Policy.blockers(r.before).isEmpty())throw new Exception(String.join("；",Policy.blockers(r.before)));
   b.refreshHal(r.before);
   if(!Policy.blockers(r.before).isEmpty())throw new Exception(String.join("；",Policy.blockers(r.before)));
   b.checkDeadline();r.attempted=true;b.setActiveB();r.completed=true;
  }catch(Exception e){r.error=e.getClass().getSimpleName()+": "+e.getMessage();}
  if(r.attempted){
   try{r.after=b.readAfter();}catch(Exception e){r.afterError=e.getClass().getSimpleName()+": "+e.getMessage();}
  }
  return r;
 }
}
