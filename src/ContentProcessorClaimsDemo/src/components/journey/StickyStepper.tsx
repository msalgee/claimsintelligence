import { Body1, Caption1, makeStyles, tokens } from '@fluentui/react-components';
import { CheckmarkCircle16Filled, Circle16Regular } from '@fluentui/react-icons';
import { motion } from 'framer-motion';
import { Fragment } from 'react';
import { useClaimStore } from '../../store/claimStore';
import { SECTIONS } from '../../pages/journey/sections';

const useStyles = makeStyles({
  root: {
    position: 'sticky',
    top: 0,
    zIndex: 10,
    backgroundColor: tokens.colorNeutralBackground1,
    borderBottomWidth: '1px',
    borderBottomStyle: 'solid',
    borderBottomColor: tokens.colorNeutralStroke2,
    paddingTop: '12px',
    paddingBottom: '12px',
    paddingLeft: '24px',
    paddingRight: '24px',
  },
  inner: {
    maxWidth: '1200px',
    marginLeft: 'auto',
    marginRight: 'auto',
    display: 'flex',
    alignItems: 'center',
    columnGap: '4px',
    overflowX: 'auto',
  },
  node: {
    display: 'flex',
    alignItems: 'center',
    columnGap: '6px',
    paddingTop: '6px',
    paddingBottom: '6px',
    paddingLeft: '8px',
    paddingRight: '8px',
    borderTopLeftRadius: '999px',
    borderTopRightRadius: '999px',
    borderBottomRightRadius: '999px',
    borderBottomLeftRadius: '999px',
    cursor: 'pointer',
    color: tokens.colorNeutralForeground3,
    backgroundColor: 'transparent',
    transitionProperty: 'background-color, color',
    transitionDuration: '160ms',
    transitionTimingFunction: 'ease-out',
    flexShrink: 0,
    ':hover': {
      backgroundColor: tokens.colorNeutralBackground2,
      color: tokens.colorNeutralForeground1,
    },
  },
  nodeActive: {
    color: tokens.colorNeutralForeground1,
    backgroundColor: 'rgba(0, 188, 190, 0.16)',
  },
  nodeDone: {
    color: tokens.colorNeutralForeground2,
  },
  nodeLocked: {
    cursor: 'not-allowed',
    opacity: 0.45,
    ':hover': {
      backgroundColor: 'transparent',
      color: tokens.colorNeutralForeground3,
    },
  },
  separator: {
    height: '1px',
    width: '4px',
    backgroundColor: tokens.colorNeutralStroke2,
    flexShrink: 0,
  },
  index: {
    fontVariantNumeric: 'tabular-nums',
    opacity: 0.6,
  },
  label: {
    whiteSpace: 'nowrap',
  },
});

interface StickyStepperProps {
  onStepClick: (step: number) => void;
}

export function StickyStepper({ onStepClick }: StickyStepperProps) {
  const styles = useStyles();
  const currentStep = useClaimStore((s) => s.currentStep);
  const completed = useClaimStore((s) => s.completed);

  return (
    <motion.nav
      className={styles.root}
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      aria-label="Claim journey progress"
    >
      <div className={styles.inner}>
        {SECTIONS.map((section, idx) => {
          const isDone = completed.has(section.step);
          const isActive = section.step === currentStep;
          const isLocked = !isDone && !isActive && section.step > currentStep;
          const classNames = [
            styles.node,
            isActive ? styles.nodeActive : '',
            isDone && !isActive ? styles.nodeDone : '',
            isLocked ? styles.nodeLocked : '',
          ]
            .filter(Boolean)
            .join(' ');
          return (
            <Fragment key={section.step}>
              {idx > 0 && <span className={styles.separator} aria-hidden="true" />}
              <button
                type="button"
                className={classNames}
                onClick={() => !isLocked && onStepClick(section.step)}
                disabled={isLocked}
                aria-current={isActive ? 'step' : undefined}
                aria-label={`${section.step}. ${section.title}`}
                title={section.title}
              >
                {isDone ? (
                  <CheckmarkCircle16Filled style={{ color: '#00BCBE' }} />
                ) : (
                  <Circle16Regular />
                )}
                <Caption1 className={styles.index}>0{section.step}</Caption1>
                <Body1 className={styles.label}>{section.shortTitle}</Body1>
              </button>
            </Fragment>
          );
        })}
      </div>
    </motion.nav>
  );
}
