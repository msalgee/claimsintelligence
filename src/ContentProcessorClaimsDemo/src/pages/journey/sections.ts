//
// Section metadata shared by the sticky stepper and the journey page.

export interface SectionMeta {
  step: number;
  title: string;
  shortTitle: string;
  blurb: string;
}

export const SECTIONS: readonly SectionMeta[] = [
  {
    step: 1,
    title: 'Documents received',
    shortTitle: 'Documents',
    blurb: 'The claim pack lands in one place — every file, identified and ready to read.',
  },
  {
    step: 2,
    title: 'What happened',
    shortTitle: 'Story',
    blurb: 'People, vehicles, places, and a timeline of the loss.',
  },
  {
    step: 3,
    title: 'Coverage prerequisites',
    shortTitle: 'Prereqs',
    blurb: 'Required claim-file evidence before policy recommendation.',
  },
  {
    step: 4,
    title: 'Risk & integrity check',
    shortTitle: 'Risk',
    blurb: 'Look for inconsistencies and fraud signals across the pack.',
  },
  {
    step: 5,
    title: 'Adjuster review',
    shortTitle: 'Review',
    blurb: 'Review the summary and confirm the key facts.',
  },
  {
    step: 6,
    title: 'Coverage recommendation',
    shortTitle: 'Decision',
    blurb: 'Recommended outcome with the member policy and supporting guidance.',
  },
  {
    step: 7,
    title: 'Customer letter',
    shortTitle: 'Letter',
    blurb: 'Customer update prepared for adjuster review.',
  },
] as const;
