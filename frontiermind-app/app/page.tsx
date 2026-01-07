// app/page.tsx

export const dynamic = "force-dynamic";

import { supabase } from "@/lib/supabaseClient";

type Project = {
  id: number;
  name: string;
  status: string;
  description: string | null;
  created_at: string;
};

type Asset = {
  id: number;
  name: string;
  type: string;
  url: string | null;
  created_at: string;
};

function StatusBadge({ status }: { status: string }) {
  const statusStyles: Record<string, string> = {
    active: "bg-emerald-50 text-emerald-700 border-emerald-200",
    pending: "bg-amber-50 text-amber-700 border-amber-200",
    completed: "bg-blue-50 text-blue-700 border-blue-200",
    archived: "bg-stone-200 text-stone-700 border-stone-300",
  };

  const baseStyle = "px-3 py-1 text-xs font-medium border rounded-full uppercase tracking-wider";
  const style = statusStyles[status.toLowerCase()] || "bg-gray-50 text-gray-700 border-gray-200";

  return <span className={`${baseStyle} ${style}`}>{status}</span>;
}

function ProjectCard({ project, index }: { project: Project; index: number }) {
  const formattedDate = project.created_at
    ? new Date(project.created_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "—";

  return (
    <article
      className="project-card group relative bg-white border-2 border-stone-900 p-8 transition-all duration-300 hover:-translate-y-1 hover:shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]"
      style={{
        animationDelay: `${index * 100}ms`,
      }}
    >
      {/* Corner accent */}
      <div className="absolute top-0 right-0 w-16 h-16 bg-amber-400 -translate-y-3 translate-x-3 -z-10 transition-transform duration-300 group-hover:translate-x-4 group-hover:-translate-y-4" />

      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-sm font-mono text-stone-400">#{project.id}</span>
            <StatusBadge status={project.status} />
          </div>
          <h3 className="text-3xl font-serif font-bold text-stone-900 leading-tight mb-1">
            {project.name}
          </h3>
        </div>
      </div>

      <p className="text-stone-600 leading-relaxed mb-6 min-h-[3rem]">
        {project.description || "No description provided"}
      </p>

      <div className="flex items-center justify-between pt-4 border-t border-stone-200">
        <time className="text-sm font-mono text-stone-500">{formattedDate}</time>
        <svg
          className="w-5 h-5 text-stone-400 transition-transform duration-300 group-hover:translate-x-1"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>
      </div>
    </article>
  );
}

function AssetCard({ asset, index }: { asset: Asset; index: number }) {
  const formattedDate = asset.created_at
    ? new Date(asset.created_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "—";

  return (
    <article
      className="asset-card group relative bg-white border-2 border-stone-900 p-8 transition-all duration-300 hover:-translate-y-1 hover:shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]"
      style={{
        animationDelay: `${index * 100}ms`,
      }}
    >
      {/* Corner accent */}
      <div className="absolute top-0 right-0 w-16 h-16 bg-blue-400 -translate-y-3 translate-x-3 -z-10 transition-transform duration-300 group-hover:translate-x-4 group-hover:-translate-y-4" />

      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-sm font-mono text-stone-400">#{asset.id}</span>
            <span className="px-3 py-1 text-xs font-medium border rounded-full uppercase tracking-wider bg-blue-50 text-blue-700 border-blue-200">
              {asset.type}
            </span>
          </div>
          <h3 className="text-3xl font-serif font-bold text-stone-900 leading-tight mb-1">
            {asset.name}
          </h3>
        </div>
      </div>

      {asset.url && (
        <p className="text-stone-600 leading-relaxed mb-6 min-h-[3rem] font-mono text-sm break-all">
          {asset.url}
        </p>
      )}

      <div className="flex items-center justify-between pt-4 border-t border-stone-200">
        <time className="text-sm font-mono text-stone-500">{formattedDate}</time>
        <svg
          className="w-5 h-5 text-stone-400 transition-transform duration-300 group-hover:translate-x-1"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>
      </div>
    </article>
  );
}

export default async function Home() {
  const { data: projects, error: projectsError } = await supabase
    .from("projects")
    .select("*")
    .order("created_at", { ascending: false });

  const { data: assets, error: assetsError } = await supabase
    .from("assets")
    .select("*")
    .order("created_at", { ascending: false });

  if (projectsError) {
    console.error("Supabase projects error:", projectsError);
  }

  if (assetsError) {
    console.error("Supabase assets error:", assetsError);
  }

  return (
    <div className="min-h-screen bg-stone-50">
      <div className="mx-auto max-w-7xl px-6 py-16">
        {/* Projects Section */}
        <section className="mb-20">
          <header className="header-animate mb-16">
            <div className="flex items-end gap-4 mb-4">
              <h1 className="text-7xl font-serif font-black text-stone-900 leading-none">
                Projects
              </h1>
              <span className="text-2xl font-mono text-amber-500 mb-2">
                {projects?.length || 0}
              </span>
            </div>
            <div className="h-1 w-32 bg-amber-400" />
          </header>

          {/* Error State */}
          {projectsError && (
            <div className="border-2 border-red-500 bg-red-50 p-6 mb-8">
              <p className="font-mono text-red-800">
                <span className="font-bold">Error:</span> {projectsError.message}
              </p>
            </div>
          )}

          {/* Empty State */}
          {!projectsError && (!projects || projects.length === 0) && (
            <div className="text-center py-20">
              <div className="inline-block border-2 border-stone-900 bg-white p-12">
                <p className="text-xl font-serif text-stone-600">
                  No projects found
                </p>
              </div>
            </div>
          )}

          {/* Projects Grid */}
          {projects && projects.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
              {projects.map((project: Project, index: number) => (
                <ProjectCard key={project.id} project={project} index={index} />
              ))}
            </div>
          )}
        </section>

        {/* Assets Section */}
        <section>
          <header className="header-animate mb-16">
            <div className="flex items-end gap-4 mb-4">
              <h1 className="text-7xl font-serif font-black text-stone-900 leading-none">
                Assets
              </h1>
              <span className="text-2xl font-mono text-blue-500 mb-2">
                {assets?.length || 0}
              </span>
            </div>
            <div className="h-1 w-32 bg-blue-400" />
          </header>

          {/* Error State */}
          {assetsError && (
            <div className="border-2 border-red-500 bg-red-50 p-6 mb-8">
              <p className="font-mono text-red-800">
                <span className="font-bold">Error:</span> {assetsError.message}
              </p>
            </div>
          )}

          {/* Empty State */}
          {!assetsError && (!assets || assets.length === 0) && (
            <div className="text-center py-20">
              <div className="inline-block border-2 border-stone-900 bg-white p-12">
                <p className="text-xl font-serif text-stone-600">
                  No assets found
                </p>
              </div>
            </div>
          )}

          {/* Assets Grid */}
          {assets && assets.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
              {assets.map((asset: Asset, index: number) => (
                <AssetCard key={asset.id} asset={asset} index={index} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
