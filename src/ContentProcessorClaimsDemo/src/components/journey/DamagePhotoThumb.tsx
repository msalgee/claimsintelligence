//
// Stylized damage-photo thumbnail used in Section 1's damage_photo.jpg card
// while the real uploaded image is loading or unavailable. Mimics an
// AI-annotated incident photo:
// dark gradient backdrop suggesting low-light scene, simplified front-3/4
// vehicle silhouette with crumple lines, and two highlighted damage zones
// matching the sample claim's damage cues.

export function DamagePhotoThumb({ height = 120 }: { height?: number }) {
  return (
    <svg
      role="img"
      aria-label="AI-annotated damage photo thumbnail"
      viewBox="0 0 320 180"
      xmlns="http://www.w3.org/2000/svg"
      style={{
        width: '100%',
        height,
        display: 'block',
        borderRadius: '6px',
        backgroundColor: '#0b1620',
      }}
    >
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1a2a3a" />
          <stop offset="60%" stopColor="#0e1a25" />
          <stop offset="100%" stopColor="#070d12" />
        </linearGradient>
        <linearGradient id="body" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3a4a5e" />
          <stop offset="100%" stopColor="#1c2530" />
        </linearGradient>
        <radialGradient id="head" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#fff7c2" />
          <stop offset="60%" stopColor="#9c8a3a" />
          <stop offset="100%" stopColor="#2a2410" />
        </radialGradient>
        <radialGradient id="pulse" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ff5d4d" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#ff5d4d" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Sky / scene */}
      <rect width="320" height="180" fill="url(#sky)" />

      {/* Road */}
      <path d="M0 150 L320 150 L320 180 L0 180 Z" fill="#0a1218" />
      <path d="M40 168 L80 168 M120 168 L160 168 M200 168 L240 168 M280 168 L320 168"
            stroke="#28323d" strokeWidth="2" strokeDasharray="6 6" />

      {/* Rough vehicle silhouette - front 3/4 */}
      <path
        d="M55 140
           Q55 95 95 92
           L195 92
           Q235 95 245 110
           L260 130
           Q265 138 260 145
           L52 145
           Q48 142 55 140 Z"
        fill="url(#body)"
      />
      {/* Windshield */}
      <path d="M100 95 Q100 75 130 73 L185 73 Q210 75 215 95 Z" fill="#3a4a5e" opacity="0.7" />
      {/* Bumper crumple - jagged */}
      <path
        d="M55 140 L62 132 L70 138 L78 130 L86 138 L94 132 L102 140 L110 132 L118 140"
        stroke="#cf3f2e"
        strokeWidth="2"
        fill="none"
        opacity="0.85"
      />
      {/* Hood crease lines */}
      <path d="M120 108 L165 100 M135 118 L180 110" stroke="#0a1218" strokeWidth="1" opacity="0.6" />
      {/* Headlights - left broken */}
      <ellipse cx="68" cy="125" rx="10" ry="5" fill="#1a1a1a" />
      <path d="M60 125 L76 125 M68 121 L68 129" stroke="#cf3f2e" strokeWidth="1.4" />
      {/* Headlight - right intact */}
      <ellipse cx="232" cy="125" rx="10" ry="5" fill="url(#head)" opacity="0.9" />

      {/* Damage zone 1 - bumper */}
      <circle cx="80" cy="135" r="22" fill="url(#pulse)" />
      <circle cx="80" cy="135" r="12" stroke="#ff5d4d" strokeWidth="1.5" fill="none" />
      <text x="80" y="138" textAnchor="middle" fontSize="9" fill="#ff5d4d" fontFamily="system-ui" fontWeight="600">
        1
      </text>

      {/* Damage zone 2 - hood */}
      <circle cx="155" cy="100" r="20" fill="url(#pulse)" />
      <circle cx="155" cy="100" r="11" stroke="#ff5d4d" strokeWidth="1.5" fill="none" />
      <text x="155" y="103" textAnchor="middle" fontSize="9" fill="#ff5d4d" fontFamily="system-ui" fontWeight="600">
        2
      </text>

      {/* AI overlay corner marks */}
      <g stroke="#00BCBE" strokeWidth="1.4" fill="none">
        <path d="M8 8 L8 22 M8 8 L22 8" />
        <path d="M312 8 L312 22 M312 8 L298 8" />
        <path d="M8 172 L8 158 M8 172 L22 172" />
        <path d="M312 172 L312 158 M312 172 L298 172" />
      </g>
      <text x="12" y="172" fontSize="8" fill="#00BCBE" fontFamily="ui-monospace,monospace">
        VISION · 2 zones detected
      </text>
      <text x="308" y="172" fontSize="8" fill="#00BCBE" fontFamily="ui-monospace,monospace" textAnchor="end">
        4032×3024 · EXIF 2026-04-13
      </text>
    </svg>
  );
}
