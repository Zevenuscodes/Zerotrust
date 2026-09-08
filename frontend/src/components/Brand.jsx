export default function Brand({ subtitle }) {
  return (
    <div className="brand">
      <svg width="30" height="30" viewBox="0 0 30 30" fill="none">
        <circle cx="15" cy="15" r="14" fill="var(--accent-bg)" stroke="var(--accent)" strokeWidth="1.5" />
        <circle cx="15" cy="15" r="7.5" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
        <circle cx="15" cy="15" r="3" fill="var(--success)" />
      </svg>
      <div>
        <h1 className="brand-title">Zero Trust</h1>
        {subtitle && <p className="brand-subtitle">{subtitle}</p>}
      </div>
    </div>
  );
}
