//
// Wraps a journey section. Renders one of three modes:
//   - locked: dim placeholder (no children, no fetch — purely visual gap)
//   - active: full children, "Next" button at bottom
//   - done:   compact summary card (one-line outcome + "Edit" button)
// Smoothly animates between modes via framer-motion.

import {
  Body1,
  Button,
  Caption1,
  Subtitle1,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowRight20Regular,
  CheckmarkCircle20Filled,
  Edit16Regular,
  LockClosed20Regular,
} from '@fluentui/react-icons';
import { AnimatePresence, motion } from 'framer-motion';
import type { ReactNode } from 'react';

const useStyles = makeStyles({
  root: {
    maxWidth: '1080px',
    marginLeft: 'auto',
    marginRight: 'auto',
    paddingTop: '32px',
    paddingBottom: '32px',
    paddingLeft: '24px',
    paddingRight: '24px',
    scrollMarginTop: '96px',
  },
  card: {
    paddingTop: '32px',
    paddingBottom: '32px',
    paddingLeft: '32px',
    paddingRight: '32px',
    borderTopWidth: '1px',
    borderRightWidth: '1px',
    borderBottomWidth: '1px',
    borderLeftWidth: '1px',
    borderTopStyle: 'solid',
    borderRightStyle: 'solid',
    borderBottomStyle: 'solid',
    borderLeftStyle: 'solid',
    borderTopColor: tokens.colorNeutralStroke2,
    borderRightColor: tokens.colorNeutralStroke2,
    borderBottomColor: tokens.colorNeutralStroke2,
    borderLeftColor: tokens.colorNeutralStroke2,
    borderTopLeftRadius: '16px',
    borderTopRightRadius: '16px',
    borderBottomRightRadius: '16px',
    borderBottomLeftRadius: '16px',
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow16,
  },
  cardLocked: {
    opacity: 0.45,
    boxShadow: 'none',
  },
  cardDone: {
    paddingTop: '20px',
    paddingBottom: '20px',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    columnGap: '12px',
    rowGap: '6px',
    marginBottom: '8px',
  },
  eyebrow: {
    color: '#00BCBE',
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
  },
  techPill: {
    display: 'inline-flex',
    alignItems: 'center',
    columnGap: '6px',
    paddingTop: '3px',
    paddingBottom: '3px',
    paddingLeft: '10px',
    paddingRight: '10px',
    borderRadius: '999px',
    fontSize: '11px',
    fontWeight: 500,
    letterSpacing: '0.02em',
    color: tokens.colorNeutralForeground2,
    backgroundColor: 'rgba(0, 188, 190, 0.12)',
    borderTopWidth: '1px',
    borderRightWidth: '1px',
    borderBottomWidth: '1px',
    borderLeftWidth: '1px',
    borderTopStyle: 'solid',
    borderRightStyle: 'solid',
    borderBottomStyle: 'solid',
    borderLeftStyle: 'solid',
    borderTopColor: 'rgba(0, 188, 190, 0.35)',
    borderRightColor: 'rgba(0, 188, 190, 0.35)',
    borderBottomColor: 'rgba(0, 188, 190, 0.35)',
    borderLeftColor: 'rgba(0, 188, 190, 0.35)',
  },
  techPillDot: {
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    backgroundColor: '#00BCBE',
    boxShadow: '0 0 6px rgba(0, 188, 190, 0.7)',
  },
  blurb: {
    color: tokens.colorNeutralForeground2,
    marginBottom: '24px',
    marginTop: '4px',
    display: 'block',
  },
  title: {
    display: 'block',
  },
  doneRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    columnGap: '16px',
  },
  doneLeft: {
    display: 'flex',
    alignItems: 'center',
    columnGap: '12px',
    minWidth: 0,
  },
  doneSummary: {
    color: tokens.colorNeutralForeground2,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  footer: {
    marginTop: '24px',
    display: 'flex',
    justifyContent: 'flex-end',
  },
  // Primary CTA — yellow on navy. Overrides Fluent's brand button to give the
  // "next" action a distinct visual treatment vs. secondary navy buttons.
  ctaButton: {
    backgroundColor: '#FFCF03',
    color: '#001272',
    fontWeight: 600,
    borderTopColor: '#FFCF03',
    borderRightColor: '#FFCF03',
    borderBottomColor: '#FFCF03',
    borderLeftColor: '#FFCF03',
    ':hover': {
      backgroundColor: '#FFD933',
      color: '#001272',
      borderTopColor: '#FFD933',
      borderRightColor: '#FFD933',
      borderBottomColor: '#FFD933',
      borderLeftColor: '#FFD933',
    },
    ':hover:active': {
      backgroundColor: '#E6BB00',
      color: '#001272',
    },
  },
});

export type JourneyMode = 'locked' | 'active' | 'done';

interface JourneySectionProps {
  step: number;
  title: string;
  blurb: string;
  mode: JourneyMode;
  doneSummary?: string;
  onNext?: () => void;
  onEdit?: () => void;
  nextLabel?: string;
  nextDisabled?: boolean;
  /** Subtle 'powered by' tag, e.g. 'Azure AI Content Understanding · Foundry'. */
  techStack?: string;
  /** Hover/focus detail for the powered-by tag. */
  techDetails?: string;
  children?: ReactNode;
}

export function JourneySection({
  step,
  title,
  blurb,
  mode,
  doneSummary,
  onNext,
  onEdit,
  nextLabel = 'Confirm and continue',
  nextDisabled,
  techStack,
  techDetails,
  children,
}: JourneySectionProps) {
  const styles = useStyles();
  const sectionId = `section-${step}`;

  return (
    <section id={sectionId} className={styles.root} aria-labelledby={`${sectionId}-title`}>
      <motion.div
        layout
        transition={{ layout: { duration: 0.4, ease: 'easeOut' } }}
        className={[
          styles.card,
          mode === 'locked' ? styles.cardLocked : '',
          mode === 'done' ? styles.cardDone : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        <AnimatePresence mode="wait" initial={false}>
          {mode === 'done' ? (
            <motion.div
              key="done"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className={styles.doneRow}
            >
              <div className={styles.doneLeft}>
                <CheckmarkCircle20Filled style={{ color: '#00BCBE', flexShrink: 0 }} />
                <div style={{ minWidth: 0 }}>
                  <Caption1 className={styles.eyebrow}>Step 0{step}</Caption1>
                  <Body1 id={`${sectionId}-title`} style={{ display: 'block', marginTop: '2px' }}>
                    <strong>{title}</strong>
                    {doneSummary && (
                      <span className={styles.doneSummary}> · {doneSummary}</span>
                    )}
                  </Body1>
                </div>
              </div>
              {onEdit && (
                <Button appearance="subtle" icon={<Edit16Regular />} onClick={onEdit}>
                  Edit
                </Button>
              )}
            </motion.div>
          ) : (
            <motion.div
              key="open"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className={styles.header}>
                {mode === 'locked' && <LockClosed20Regular />}
                <Caption1 className={styles.eyebrow}>Step 0{step}</Caption1>
                {techStack && (
                  <Tooltip
                    content={techDetails ?? `Powered by ${techStack}`}
                    relationship="description"
                    positioning="above"
                  >
                    <span
                      className={styles.techPill}
                      tabIndex={0}
                      aria-label={`Powered by ${techStack}`}
                    >
                      <span className={styles.techPillDot} aria-hidden="true" />
                      {techStack}
                    </span>
                  </Tooltip>
                )}
              </div>
              <Subtitle1 as="h2" id={`${sectionId}-title`} style={{ display: 'block' }}>
                {title}
              </Subtitle1>
              <Body1 as="p" className={styles.blurb} style={{ display: 'block' }}>
                {blurb}
              </Body1>
              {mode === 'active' && (
                <>
                  <div>{children}</div>
                  {onNext && (
                    <div className={styles.footer}>
                      <Button
                        appearance="primary"
                        size="large"
                        iconPosition="after"
                        icon={<ArrowRight20Regular />}
                        onClick={onNext}
                        disabled={nextDisabled}
                        className={styles.ctaButton}
                      >
                        {nextLabel}
                      </Button>
                    </div>
                  )}
                </>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </section>
  );
}
