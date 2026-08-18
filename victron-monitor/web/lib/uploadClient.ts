// Raw browser -> Supabase Storage upload, deliberately NOT using
// `@supabase/supabase-js`'s `uploadToSignedUrl()` helper (PLAN_PHASE14.md
// §1.2 rule 2: "there is no browser Supabase client at all — not even an
// anon-key one"). Pulling in `@supabase/supabase-js` here — even just for
// its Storage helper, even with no key configured — would mean this file
// constructs a `SupabaseClient` in a client component, which is exactly the
// "just quickly add one" §1.2 rule 2 is written to make structurally
// awkward to do by accident.
//
// A signed upload URL is not a Supabase-SDK-only concept, though — it's a
// plain HTTP endpoint with the auth token embedded in the query string
// (`app/api/uploads/sign` hands the browser the full `signedUrl`, nothing
// else). So this file reimplements the same request the SDK's
// `uploadToSignedUrl()` sends — a `PUT` with a `multipart/form-data` body
// carrying `cacheControl` and the file itself under an empty field name,
// `x-upsert` header set to `false` — using nothing but `XMLHttpRequest`
// (chosen over `fetch()` specifically because it's the only browser-native
// way to get upload progress events, which `UploadManager.tsx` needs for
// its progress bar).
export type UploadProgressHandler = (percent: number) => void;

export function uploadFileToSignedUrl(signedUrl: string, file: File, onProgress?: UploadProgressHandler): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append('cacheControl', '3600');
    form.append('', file);

    const xhr = new XMLHttpRequest();
    xhr.open('PUT', signedUrl, true);
    xhr.setRequestHeader('x-upsert', 'false');

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed (${xhr.status}).`));
      }
    };
    xhr.onerror = () => reject(new Error('Upload failed — network error.'));
    xhr.onabort = () => reject(new Error('Upload cancelled.'));

    xhr.send(form);
  });
}
