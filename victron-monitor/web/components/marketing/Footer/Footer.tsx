import styles from './Footer.module.css';

export function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={`wrap ${styles.inner}`}>
        <div className={styles.brand}>
          <svg className={styles.mark} viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M15 2 L27 8.5 V21.5 L15 28 L3 21.5 V8.5 Z" stroke="#6F93A6" strokeWidth="1.6" fill="none" />
          </svg>
          VRM Monitor by Pauly &amp; Co. — Atenas, Costa Rica
        </div>
        <div className={styles.links}>
          <a href="mailto:proyectos@paulyco.com">proyectos@paulyco.com</a>
          <a href="#how">How it works</a>
          <a href="#modules">What&apos;s inside</a>
        </div>
      </div>
    </footer>
  );
}
