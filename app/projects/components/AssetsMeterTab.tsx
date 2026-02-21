'use client'

import { ProjectTableTab, type Column } from './ProjectTableTab'

interface AssetsMeterTabProps {
  assets: Record<string, unknown>[]
  meters: Record<string, unknown>[]
  assetColumns: Column[]
  meterColumns: Column[]
  projectId?: number
  onSaved?: () => void
  editMode?: boolean
}

export function AssetsMeterTab({ assets, meters, assetColumns, meterColumns, projectId, onSaved, editMode }: AssetsMeterTabProps) {
  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-sm font-medium text-slate-700 mb-3">Assets</h3>
        <ProjectTableTab
          data={assets}
          columns={assetColumns}
          emptyMessage="No assets found"
          entity="assets"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
        />
      </div>
      <div>
        <h3 className="text-sm font-medium text-slate-700 mb-3">Meters</h3>
        <ProjectTableTab
          data={meters}
          columns={meterColumns}
          emptyMessage="No meters found"
          entity="meters"
          projectId={projectId}
          onSaved={onSaved}
          editMode={editMode}
        />
      </div>
    </div>
  )
}
