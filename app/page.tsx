// app/page.tsx

export const dynamic = "force-dynamic"; // ensure server-side runtime fetching

import Image from "next/image";
import { supabase } from "@/lib/supabaseClient";

// ⬇️ Make this async so we can await Supabase
export default async function Home() {
  // ⬇️ Fetch data from Supabase
  const { data: projects, error } = await supabase
    .from("projects")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    console.error("Supabase error:", error);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex w-full max-w-5xl flex-col gap-8 p-8 bg-white dark:bg-black">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Image src="/next.svg" alt="Next" width={80} height={20} />
            <h1 className="text-2xl font-semibold">Projects</h1>
          </div>
        </header>

        <section>
          <h2 className="text-lg font-medium mb-4">Projects table</h2>

          {error && (
            <div className="text-red-600 mb-4">
              Error loading projects: {error.message}
            </div>
          )}

          {!error && (!projects || projects.length === 0) && (
            <div className="text-zinc-600">No projects found.</div>
          )}

          {projects && projects.length > 0 && (
            <div className="overflow-x-auto rounded border">
              <table className="min-w-full divide-y">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left">ID</th>
                    <th className="px-4 py-2 text-left">Name</th>
                    <th className="px-4 py-2 text-left">Status</th>
                    <th className="px-4 py-2 text-left">Description</th>
                    <th className="px-4 py-2 text-left">Created At</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((p: any) => (
                    <tr key={p.id} className="odd:bg-white even:bg-gray-50">
                      <td className="px-4 py-2 text-sm">{p.id}</td>
                      <td className="px-4 py-2">{p.name}</td>
                      <td className="px-4 py-2">{p.status}</td>
                      <td className="px-4 py-2">{p.description ?? "—"}</td>
                      <td className="px-4 py-2 text-sm text-zinc-500">
                        {p.created_at
                          ? new Date(p.created_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
