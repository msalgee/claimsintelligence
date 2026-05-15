import {
  Avatar,
  Body1,
  Caption1,
  Card,
  CardHeader,
  Subtitle2,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  VehicleCar24Regular,
  Location24Regular,
  Sparkle20Filled,
  Warning20Filled,
} from '@fluentui/react-icons';
import { motion } from 'framer-motion';
import { JourneySection } from '../../../components/journey/JourneySection';
import { SectionError, SectionLoading } from '../../../components/journey/SectionStatus';
import { claimsdemo } from '../../../api/apiClient';
import { useSectionData } from '../../../api/useSectionData';
import type { JourneyMode } from '../../../components/journey/JourneySection';

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr 1fr',
    columnGap: '16px',
    '@media (max-width: 960px)': { gridTemplateColumns: '1fr' },
  },
  column: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '12px',
  },
  columnTitle: {
    color: '#00BCBE',
    fontWeight: 600,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    marginBottom: '8px',
  },
  timelineRow: {
    display: 'grid',
    gridTemplateColumns: '8px 1fr',
    columnGap: '12px',
    paddingTop: '6px',
    paddingBottom: '6px',
  },
  dot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    backgroundColor: '#00BCBE',
    marginTop: '6px',
  },
  date: {
    display: 'block',
    marginTop: '2px',
    color: tokens.colorNeutralForeground3,
  },
  timelineLabel: {
    display: 'block',
  },
  locItem: {
    display: 'grid',
    gridTemplateColumns: '24px 1fr',
    columnGap: '10px',
    rowGap: '2px',
    alignItems: 'start',
    paddingTop: '6px',
    paddingBottom: '6px',
  },
  locHeadline: {
    display: 'block',
    fontWeight: 600,
  },
  locDetail: {
    display: 'block',
    marginTop: '2px',
    color: tokens.colorNeutralForeground3,
    lineHeight: 1.4,
  },
  card: {
    paddingTop: '12px',
    paddingRight: '12px',
    paddingBottom: '12px',
    paddingLeft: '12px',
  },
  mapPlaceholder: {
    paddingTop: '12px',
    paddingRight: '12px',
    paddingBottom: '12px',
    paddingLeft: '12px',
    borderTopLeftRadius: '8px',
    borderTopRightRadius: '8px',
    borderBottomRightRadius: '8px',
    borderBottomLeftRadius: '8px',
    backgroundImage:
      'linear-gradient(135deg, rgba(43,197,180,0.10), rgba(35,105,186,0.10))',
    color: tokens.colorNeutralForeground2,
    display: 'flex',
    flexDirection: 'column',
    rowGap: '8px',
  },
  narrativeCard: {
    paddingTop: '16px',
    paddingRight: '18px',
    paddingBottom: '16px',
    paddingLeft: '18px',
    marginBottom: '16px',
    borderTopLeftRadius: '12px',
    borderTopRightRadius: '12px',
    borderBottomRightRadius: '12px',
    borderBottomLeftRadius: '12px',
    backgroundImage:
      'linear-gradient(135deg, rgba(43,197,180,0.10), rgba(35,105,186,0.06))',
  },
  narrativeHead: {
    display: 'flex',
    alignItems: 'center',
    columnGap: '8px',
    marginBottom: '8px',
  },
  insightGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
    columnGap: '8px',
    rowGap: '8px',
    marginBottom: '12px',
    '@media (max-width: 900px)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' },
  },
  insightTile: {
    paddingTop: '10px',
    paddingRight: '12px',
    paddingBottom: '10px',
    paddingLeft: '12px',
    borderTopLeftRadius: '8px',
    borderTopRightRadius: '8px',
    borderBottomRightRadius: '8px',
    borderBottomLeftRadius: '8px',
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow2,
  },
  insightLabel: {
    display: 'block',
    color: tokens.colorNeutralForeground3,
    marginBottom: '3px',
  },
  insightValue: {
    display: 'block',
    fontWeight: 600,
  },
  watchOuts: {
    marginTop: '12px',
    paddingTop: '12px',
    borderTopWidth: '1px',
    borderTopStyle: 'solid',
    borderTopColor: tokens.colorNeutralStroke3,
    display: 'flex',
    flexDirection: 'column',
    rowGap: '6px',
  },
  watchItem: {
    display: 'grid',
    gridTemplateColumns: '20px 1fr',
    columnGap: '8px',
    alignItems: 'start',
  },
});

interface Props {
  mode: JourneyMode;
  onNext: () => void;
  onEdit: () => void;
}

interface RawEntities {
  generation_source?: 'fixture';
  people?: Array<Record<string, unknown>>;
  vehicles?: Array<Record<string, unknown>>;
  locations?: Array<Record<string, unknown>>;
  timeline?: Array<Record<string, unknown>>;
  narrative?: string;
  watch_outs?: string[];
}

function s(v: unknown): string {
  return v == null ? '' : String(v);
}

function formatDate(v: unknown): string {
  const raw = s(v);
  if (!raw) return '';
  // Date-only strings (YYYY-MM-DD) parse to UTC midnight which then renders
  // as the previous calendar day in negative-UTC timezones. Parse the
  // components manually so the displayed date matches the source string.
  const ymd = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (ymd) {
    const d = new Date(Number(ymd[1]), Number(ymd[2]) - 1, Number(ymd[3]));
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  // Render full datetimes as "Jan 5, 2026" — the wall-clock time of an
  // incident isn't useful in the timeline view and creates locale-dependent
  // noise like "1/5/2026, 9:02:00 PM".
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function shortWatchOut(text: string): string {
  const lower = text.toLowerCase();
  if (lower.includes('date')) return 'Date mismatch';
  if (lower.includes('damage') || lower.includes('photo') || lower.includes('left') || lower.includes('right')) {
    return 'Damage scope mismatch';
  }
  if (lower.includes('estimate') || lower.includes('repair') || lower.includes('$')) return 'Estimate variance';
  if (lower.includes('injur')) return 'Injury status missing';
  if (lower.includes('party') || lower.includes('vehicle')) return 'Third-party details missing';
  return text.length > 34 ? `${text.slice(0, 31).trim()}...` : text;
}

// Distinguish hard cross-document contradictions ("the police report says
// 14:35 but the claim form says 16:10") from softer attention points
// ("third-party insurer not yet confirmed"). Conflicts render red so an
// adjuster can spot them at a glance; the rest stay amber.
const CONFLICT_KEYWORDS = [
  'conflict',
  'contradict',
  'mismatch',
  'discrepan',
  'disagree',
  'differs',
  'inconsisten',
  'does not match',
  "doesn't match",
];
function isConflict(text: string): boolean {
  const lower = text.toLowerCase();
  return CONFLICT_KEYWORDS.some((k) => lower.includes(k));
}

export function Step2Entities({ mode, onNext, onEdit }: Props) {
  const styles = useStyles();
  const { loading, error, data: raw } = useSectionData<RawEntities>(
    3,
    (id) => claimsdemo.entities(id) as unknown as Promise<RawEntities>,
    mode !== 'locked',
  );
  const data = raw
    ? {
        people: raw.people ?? [],
        vehicles: raw.vehicles ?? [],
        locations: raw.locations ?? [],
        timeline: raw.timeline ?? [],
        narrative: typeof raw.narrative === 'string' ? raw.narrative.trim() : '',
        watchOuts: Array.isArray(raw.watch_outs)
          ? raw.watch_outs.filter((w) => typeof w === 'string' && w.trim()).map((w) => String(w))
          : [],
      }
    : null;
  const doneSummary = data
    ? `${data.people.length} people · ${data.vehicles.length} vehicle · ${data.timeline.length} events`
    : undefined;
  const insightValues = data
    ? [
        data.watchOuts.length > 0 ? 'Investigate before settlement' : 'No major gaps flagged',
        ...data.watchOuts.map((w) => ({ label: shortWatchOut(w), conflict: isConflict(w) })),
      ].slice(0, 4)
    : [];
  const fromFixture = raw?.generation_source === 'fixture';

  return (
    <JourneySection
      step={2}
      techStack={fromFixture ? 'Local fixture data' : 'Foundry Agent Service · GPT-5.1'}
      techDetails={
        fromFixture
          ? 'The API is in local fixture mode because Foundry project/model configuration is not set.'
          : 'A Foundry Agent Service agent uses GPT-5.1 to turn the processed claim text into the incident story, parties, vehicles, locations, and timeline.'
      }
      title="What happened"
      blurb="A clear claim story with the parties, vehicles, locations, timeline, and any facts that need attention."
      mode={mode}
      doneSummary={doneSummary}
      onNext={onNext}
      onEdit={onEdit}
      nextLabel="Continue to coverage check"
      nextDisabled={loading || !!error}
    >
      {loading && <SectionLoading label="Building claim story…" />}
      {error && <SectionError message={error} />}
      {!loading && !error && data && (
        <>
          {(data.narrative || data.watchOuts.length > 0) && (
            <motion.div
              className={styles.narrativeCard}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className={styles.narrativeHead}>
                <Sparkle20Filled style={{ color: '#00BCBE' }} />
                <Subtitle2>What we're looking at</Subtitle2>
              </div>
              {insightValues.length > 0 && (
                <div className={styles.insightGrid}>
                  {insightValues.map((value, idx) => {
                    const isString = typeof value === 'string';
                    const text = isString ? value : value.label;
                    const conflict = !isString && value.conflict;
                    return (
                      <div
                        key={`${text}-${idx}`}
                        className={styles.insightTile}
                        style={
                          conflict
                            ? {
                                borderLeft: `3px solid ${tokens.colorPaletteRedForeground1}`,
                              }
                            : undefined
                        }
                      >
                        <Caption1 className={styles.insightLabel}>
                          {idx === 0 ? 'Claim read' : conflict ? 'Conflict' : 'Attention point'}
                        </Caption1>
                        <Body1
                          className={styles.insightValue}
                          style={
                            conflict ? { color: tokens.colorPaletteRedForeground1 } : undefined
                          }
                        >
                          {text}
                        </Body1>
                      </div>
                    );
                  })}
                </div>
              )}
              {data.narrative && (
                <Body1 style={{ color: tokens.colorNeutralForeground1, lineHeight: 1.55 }}>
                  {data.narrative}
                </Body1>
              )}
              {data.watchOuts.length > 0 && (
                <div className={styles.watchOuts}>
                  <Caption1
                    style={{
                      color: '#00BCBE',
                      fontWeight: 600,
                      letterSpacing: '0.06em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Things to look out for
                  </Caption1>
                  {data.watchOuts.map((w, i) => {
                    const conflict = isConflict(w);
                    return (
                      <div key={i} className={styles.watchItem}>
                        <Warning20Filled
                          style={{
                            color: conflict
                              ? tokens.colorPaletteRedForeground1
                              : '#FFCF03',
                          }}
                        />
                        <Body1
                          style={
                            conflict
                              ? { color: tokens.colorPaletteRedForeground1, fontWeight: 600 }
                              : undefined
                          }
                        >
                          {conflict ? `Conflict — ${w}` : w}
                        </Body1>
                      </div>
                    );
                  })}
                </div>
              )}
            </motion.div>
          )}
          <div className={styles.grid}>
          <div className={styles.column}>
            <Caption1 className={styles.columnTitle}>Timeline</Caption1>
            {data.timeline.map((entry, idx) => {
              const dateRaw = entry.date ?? entry.timestamp;
              return (
                <motion.div
                  key={`${s(dateRaw)}-${idx}`}
                  className={styles.timelineRow}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: idx * 0.04 }}
                >
                  <span className={styles.dot} />
                  <div>
                    <Body1 className={styles.timelineLabel}>{s(entry.label) || s(entry.detail)}</Body1>
                    <Caption1 className={styles.date}>{formatDate(dateRaw)}</Caption1>
                  </div>
                </motion.div>
              );
            })}
          </div>
          <div className={styles.column}>
            <Caption1 className={styles.columnTitle}>People</Caption1>
            {data.people.map((p, idx) => {
              const name = s(p.name) || 'Unknown';
              const role = s(p.role);
              const contact = s(p.contact) || s(p.detail);
              return (
                <Card key={s(p.id) || `${name}-${idx}`} className={styles.card}>
                  <CardHeader
                    image={<Avatar name={name} size={32} />}
                    header={<Subtitle2>{name}</Subtitle2>}
                    description={
                      <Caption1>
                        {role}
                        {role && contact ? ' · ' : ''}
                        {contact}
                      </Caption1>
                    }
                  />
                </Card>
              );
            })}
          </div>
          <div className={styles.column}>
            <Caption1 className={styles.columnTitle}>Vehicles & Locations</Caption1>
            {data.vehicles.map((v, idx) => {
              const headline =
                [s(v.year), s(v.make), s(v.model)].filter(Boolean).join(' ') ||
                s(v.description) ||
                'Vehicle';
              const detail =
                [s(v.vin) && `VIN ${s(v.vin)}`, s(v.registration) && `Reg ${s(v.registration)}`]
                  .filter(Boolean)
                  .join(' · ') || s(v.detail);
              return (
                <Card key={s(v.id) || `${headline}-${idx}`} className={styles.card}>
                  <CardHeader
                    image={<VehicleCar24Regular />}
                    header={<Subtitle2>{headline}</Subtitle2>}
                    description={<Caption1>{detail}</Caption1>}
                  />
                </Card>
              );
            })}
            <div className={styles.mapPlaceholder}>
              <Body1 style={{ display: 'flex', alignItems: 'center', columnGap: '8px' }}>
                <Location24Regular />
                <span>{data.locations.length} location{data.locations.length === 1 ? '' : 's'}</span>
              </Body1>
              {data.locations.map((loc, idx) => {
                const headline = s(loc.description) || s(loc.name) || s(loc.address) || `Location ${idx + 1}`;
                const detail = s(loc.detail) || s(loc.address) || s(loc.role) || '';
                return (
                  <div key={`${headline}-${idx}`} className={styles.locItem}>
                    <Location24Regular style={{ color: '#00BCBE' }} />
                    <div>
                      <Body1 className={styles.locHeadline}>{headline}</Body1>
                      {detail && detail !== headline && (
                        <Caption1 className={styles.locDetail}>{detail}</Caption1>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          </div>
        </>
      )}
    </JourneySection>
  );
}
