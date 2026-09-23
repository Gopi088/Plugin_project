export const SECTIONS={summary:['Summary','text'],workExperience:['Experience','itemList'],education:['Education','itemList'],personalProjects:['Projects','itemList'],additional:['Skills & qualifications','stringList']};
export function normalizeResume(data={}) {
  const result=structuredClone(data);
  result.personalInfo||={};result.summary||='';
  for(const key of ['workExperience','education','personalProjects'])result[key]||=[];
  result.additional||={};
  for(const key of ['technicalSkills','languages','certificationsTraining','awards'])result.additional[key]||=[];
  result.customSections||={};
  if(!Array.isArray(result.sectionMeta)){
    const order=result.sectionMeta?.order||Object.keys(SECTIONS);
    const visible=result.sectionMeta?.visible||{};
    result.sectionMeta=order.map((key,index)=>({id:key,key,displayName:SECTIONS[key]?.[0]||key,
      sectionType:SECTIONS[key]?.[1]||result.customSections[key]?.sectionType||'text',isDefault:key in SECTIONS,isVisible:visible[key]!==false,order:index}));
  }
  for(const key of [...Object.keys(SECTIONS),...Object.keys(result.customSections)]){
    if(!result.sectionMeta.some(m=>m.key===key))result.sectionMeta.push({id:key,key,displayName:SECTIONS[key]?.[0]||key,
      sectionType:SECTIONS[key]?.[1]||result.customSections[key].sectionType,isDefault:key in SECTIONS,isVisible:true,order:result.sectionMeta.length});
  }
  result.sectionMeta.sort((a,b)=>a.order-b.order);
  return result;
}
export function nextId(items) {return Math.max(0,...items.map(i=>Number(i.id)||0))+1;}
