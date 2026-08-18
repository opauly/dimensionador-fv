import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listCustomers } from '@/lib/server/db/admin';
import { AdminUploadManager } from './AdminUploadManager';

export const metadata: Metadata = {
  title: 'Cargar CSV — Admin',
};

// `/admin/upload` (PLAN_PHASE14.md §2 Step 7) — same upload UX as
// `/app/upload`, but with a customer picker first: the one legitimate
// admin-session path to "upload on behalf of a chosen customer," reachable
// only from `requireAdmin()`.
export default async function AdminUploadPage() {
  await requireAdmin();
  const customers = await listCustomers();

  return (
    <div>
      <h1>Cargar exportación CSV de VRM</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Subí un archivo en nombre de un cliente. El archivo se procesa y se muestra un resumen antes de escribir nada en la base de
        datos.
      </p>
      <AdminUploadManager customers={customers} />
    </div>
  );
}
