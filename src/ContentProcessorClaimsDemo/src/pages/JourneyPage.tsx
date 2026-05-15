//
// The single-page progressive journey. All 8 sections render in one document.
// Each section component owns its own JourneySection wrapper, fetch, and body.
// "Next" advances state and auto-scrolls. Done sections collapse to a compact
// summary; clicking "Edit" reopens them. Sticky stepper drives scroll-on-click.

import { useEffect, useRef } from 'react';
import { makeStyles, tokens } from '@fluentui/react-components';
import type { JourneyMode } from '../components/journey/JourneySection';
import { StickyStepper } from '../components/journey/StickyStepper';
import { useClaimStore } from '../store/claimStore';
import { Step1Documents } from './journey/sections/Step1Documents';
import { Step2Entities } from './journey/sections/Step2Entities';
import { Step4Fraud } from './journey/sections/Step4Fraud';
import { Step3Coverage } from './journey/sections/Step3Coverage';
import { Step5Review } from './journey/sections/Step5Review';
import { Step6Recommendation } from './journey/sections/Step6Recommendation';
import { Step7Email } from './journey/sections/Step7Email';

const useStyles = makeStyles({
  root: {
    minHeight: '100%',
    backgroundImage:
      'radial-gradient(ellipse at top, rgba(43,197,180,0.06), transparent 60%), radial-gradient(ellipse at bottom right, rgba(35,105,186,0.08), transparent 60%)',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  bottomSpacer: {
    height: '40vh',
  },
});

function scrollToSection(step: number) {
  const el = document.getElementById(`section-${step}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

const SECTION_COMPONENTS = [
  Step1Documents,
  Step2Entities,
  // Coverage check (was step 5) is now step 3 — we want adjusters to see
  // "is this even covered?" before "do we trust it?".
  Step3Coverage,
  Step4Fraud,
  Step5Review,
  Step6Recommendation,
  Step7Email,
] as const;

export function JourneyPage() {
  const styles = useStyles();
  const currentStep = useClaimStore((s) => s.currentStep);
  const completed = useClaimStore((s) => s.completed);
  const markComplete = useClaimStore((s) => s.markComplete);
  const goTo = useClaimStore((s) => s.goTo);
  const lastAutoScrolledStep = useRef<number>(0);

  useEffect(() => {
    if (lastAutoScrolledStep.current !== currentStep) {
      lastAutoScrolledStep.current = currentStep;
      // Wait for the previous section's collapse animation (layout 0.4s in
      // JourneySection) to settle before scrolling, otherwise the target's
      // position shifts mid-scroll and we land past it.
      const t = setTimeout(() => scrollToSection(currentStep), 480);
      return () => clearTimeout(t);
    }
  }, [currentStep]);

  const handleStepClick = (step: number) => {
    goTo(step);
    scrollToSection(step);
  };

  return (
    <div className={styles.root}>
      <StickyStepper onStepClick={handleStepClick} />
      {SECTION_COMPONENTS.map((Component, idx) => {
        const step = idx + 1;
        const isDone = completed.has(step);
        const isActive = step === currentStep;
        const mode: JourneyMode = isActive ? 'active' : isDone ? 'done' : 'locked';
        return (
          <Component
            key={step}
            mode={mode}
            onNext={() => markComplete(step)}
            onEdit={() => handleStepClick(step)}
          />
        );
      })}
      <div className={styles.bottomSpacer} />
    </div>
  );
}
