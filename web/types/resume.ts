export interface PersonalInfo {
  name: string; title: string; email: string; phone: string; location: string;
  website: string | null; linkedin: string | null; github: string | null;
}
export interface WorkExperienceItem {
  id: number; title: string; company: string; location: string | null;
  years: string; description: string[];
}
export interface EducationItem { id: number; institution: string; degree: string; years: string; description: string | null; }
export interface ProjectItem { id: number; name: string; role: string; years: string; description: string[]; github?: string | null; website?: string | null; }
export interface AdditionalInfo { technicalSkills: string[]; languages: string[]; certificationsTraining: string[]; awards: string[]; }
export interface CustomSectionItem { id: number; title: string; subtitle?: string | null; location?: string | null; years?: string; description: string[]; }
export interface CustomSection { sectionType: 'itemList'|'text'|'stringList'; items?: CustomSectionItem[] | null; text?: string | null; strings?: string[] | null; }
/** The running Matcher API uses this list representation. */
export interface ApiSectionMeta { id: string; key: string; displayName: string; sectionType: CustomSection['sectionType']; isDefault: boolean; isVisible: boolean; order: number; }
/** Blueprint representation is accepted and adapted at the server boundary. */
export interface SectionMeta { order: string[]; visible: Record<string, boolean>; }
export interface ResumeData {
  personalInfo: PersonalInfo; summary: string; workExperience: WorkExperienceItem[];
  education: EducationItem[]; personalProjects: ProjectItem[]; additional: AdditionalInfo;
  customSections: Record<string, CustomSection>; sectionMeta?: ApiSectionMeta[] | SectionMeta;
}
export type TimelineCategory = 'work'|'education'|'project';
export interface TimelineEvent {
  id: string; category: TimelineCategory; title: string; organization: string; location: string;
  rawDateString: string; startDate: string | null; endDate: string | null; isCurrent: boolean;
  parsedStartYear: number | null; parsedEndYear: number | null;
  precision: 'month'|'year'|'unknown'; dateStatus: 'range'|'single'|'missing'|'invalid';
  durationText?: string; description: string[];
}
