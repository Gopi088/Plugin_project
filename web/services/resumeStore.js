/** Persistent draft/source snapshots; Matcher remains the saved-data authority. */
export class ResumeStore {
  constructor(name='resume-workspace') {this.name=name;this.pending=Promise.resolve();}
  async database() {
    if(!this.db)this.db=new Promise((resolve,reject)=>{
      const request=indexedDB.open(this.name,1);
      request.onupgradeneeded=()=>request.result.createObjectStore('resumes',{keyPath:'id'});
      request.onsuccess=()=>resolve(request.result);
      request.onerror=()=>reject(request.error);
    });
    return this.db;
  }
  async get(id) {
    const db=await this.database();
    return new Promise((resolve,reject)=>{
      const request=db.transaction('resumes').objectStore('resumes').get(id);
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
    });
  }
  put(record) {
    const snapshot=structuredClone(record);
    this.pending=this.pending.catch(()=>{}).then(async()=>{
      const db=await this.database();
      return new Promise((resolve,reject)=>{
        const transaction=db.transaction('resumes','readwrite');
        transaction.objectStore('resumes').put(snapshot);
        transaction.oncomplete=resolve;transaction.onerror=()=>reject(transaction.error);transaction.onabort=()=>reject(transaction.error);
      });
    });
    return this.pending;
  }
}
