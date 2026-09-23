const MIME={pdf:'application/pdf',doc:'application/msword',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',txt:'text/plain'};
export function validateFile(file) {
  const extension=file?.name?.split('.').pop().toLowerCase();
  if(!MIME[extension])throw Error('Choose a PDF, DOCX, DOC, or TXT file.');
  if(!file.size || file.size>4*1024*1024)throw Error('Choose a nonempty file no larger than 4 MB.');
  return MIME[extension];
}
export class ResumeService {
  constructor(baseUrl='/api/resume-manager', {fetchImpl=globalThis.fetch,pollInterval=1500,timeout=180000}={}) {
    this.baseUrl=baseUrl.replace(/\/$/,'');this.fetch=fetchImpl.bind(globalThis);this.pollInterval=pollInterval;this.timeout=timeout;
  }
  async request(path,options={}) {
    let response;
    try {response=await this.fetch(this.baseUrl+path,{...options,signal:options.signal?AbortSignal.any([options.signal,AbortSignal.timeout(this.timeout)]):AbortSignal.timeout(this.timeout)});}
    catch(error){if(error.name==='AbortError')throw error;throw Error('Resume service is unavailable or timed out. Your draft is kept. Check the backend and retry.');}
    if(!response.ok){
      const error=await response.json().catch(()=>({}));
      const detail=error.detail||error.error;
      throw Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(d=>`${(d.loc||[]).join('.')}: ${d.msg}`).join('; '):`Request failed (${response.status}).`);
    }
    return response;
  }
  health(options={}) {return this.request('/health',options).then(r=>r.json());}
  listResumes(options={}) {return this.request('/resumes/list?include_master=true',options).then(r=>r.json());}
  async getRecord(id,options={}) {
    try {
      const response=await this.request('/resumes?resume_id='+encodeURIComponent(id),options);
      const result=await response.json();
      if(result.data?.resume_id)return result.data;
    } catch(err) {
      try {
        const docRes=await this.fetch('/api/documents/'+encodeURIComponent(id)+'/timeline',options);
        if(docRes.ok){
          const docData=await docRes.json();
          let sourceText=docData.original_text||'';
          if(!sourceText){
            const srcRes=await this.fetch('/api/documents/'+encodeURIComponent(id)+'/source-text',options).catch(()=>null);
            if(srcRes?.ok){const srcJson=await srcRes.json();sourceText=srcJson.text||'';}
          }
          return {
            resume_id: id,
            processed_resume: {
              personalInfo: {name: docData.candidate_name||(docData.filename||'Resume').replace(/\.[^/.]+$/,'')},
              workExperience: (docData.timeline||[]).filter(t=>t.type==='EMPLOYMENT'||t.type==='INTERNSHIP').map((t,i)=>({
                id: t.id||`work-${i}`,
                title: t.title||'',
                company: t.org||'',
                location: '',
                years: t.quote||(t.start?`${t.start} - ${t.end||'Present'}`:''),
                description: t.quote?[t.quote]:[]
              })),
              education: (docData.timeline||[]).filter(t=>t.type==='EDUCATION').map((t,i)=>({
                id: t.id||`edu-${i}`,
                institution: t.org||'',
                degree: t.title||'',
                years: t.quote||(t.start?`${t.start} - ${t.end||''}`:''),
                description: t.quote?[t.quote]:[]
              })),
              personalProjects: []
            },
            raw_resume: {
              content_type: 'md',
              content: sourceText,
              processing_status: 'ready'
            }
          };
        }
      } catch(err2) {}
      throw err;
    }
    throw Error('Resume service returned an invalid response.');
  }
  async getResume(id,options={}) {
    const record=await this.getRecord(id,options);
    if(record.raw_resume?.processing_status==='failed')throw Error('Resume parsing failed. Check the model configuration in Resume Matcher.');
    if(!record.processed_resume)throw Error('Resume is still processing. Try again shortly.');
    return record.processed_resume;
  }
  async waitUntilReady(id,{signal,onStatus=()=>{}}={}) {
    const deadline=Date.now()+this.timeout;
    while(Date.now()<deadline){
      signal?.throwIfAborted();
      const record=await this.getRecord(id,{signal});
      const status=record.raw_resume?.processing_status;
      onStatus(status);
      if(status==='failed')throw Error('The file was uploaded, but parsing failed. Check Resume Matcher’s model configuration. You can reopen this resume by its ID.');
      if(status==='ready' && record.processed_resume)return {resumeId:id,resumeData:record.processed_resume,record};
      if(status==='ready')throw Error('The parser returned no structured resume data.');
      await new Promise((resolve,reject)=>{
        const stop=()=>{clearTimeout(timer);reject(new DOMException('Cancelled','AbortError'));};
        const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},this.pollInterval);
        signal?.addEventListener('abort',stop,{once:true});
      });
    }
    throw Error('Parsing is still in progress. Reopen the resume from your saved resumes to check again.');
  }
  async uploadAndParse(file,filename=file.name,{signal,onUploaded=()=>{},onStatus}={}) {
    const type=validateFile({name:filename,size:file.size});
    const form=new FormData();form.append('file',new Blob([file],{type}),filename);
    const response=await this.request('/resumes/upload',{method:'POST',body:form,signal});
    const result=await response.json();
    if(!result.resume_id)throw Error('Upload did not return a resume ID.');
    onUploaded(result.resume_id);
    return this.waitUntilReady(result.resume_id,{signal,onStatus});
  }
  async updateResume(id,resumeData,options={}) {
    const response=await this.request('/resumes/'+encodeURIComponent(id),{...options,method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(resumeData)});
    const result=await response.json();
    if(!result.data?.processed_resume)throw Error('Save response did not contain the updated resume.');
    return result.data;
  }
  getPdfDownloadUrl(id,options={}) {
    return this.baseUrl+'/resumes/'+encodeURIComponent(id)+'/pdf?'+new URLSearchParams({template:'swiss-single',pageSize:'A4',accentColor:'blue',...options});
  }
  async downloadPdf(id,options={}) {
    const url=this.getPdfDownloadUrl(id,options);
    const response=await this.request(url.slice(this.baseUrl.length));
    if(!response.headers.get('content-type')?.includes('application/pdf'))throw Error('The renderer did not return a PDF.');
    return response.blob();
  }
}
