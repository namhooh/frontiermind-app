'use client'

import type { PatchEntity } from '@/lib/api/adminClient'
import { EditableCell } from '../EditableCell'
import { str } from './helpers'

export interface EditConfig {
  fieldKey: string
  entity: PatchEntity
  entityId: number
  projectId?: number
  type?: 'text' | 'number' | 'date' | 'boolean' | 'select'
  options?: { value: number | string; label: string }[]
  selectValue?: unknown
  scaleOnSave?: number
}

export type FieldDef = [string, unknown] | [string, unknown, EditConfig]

export function FieldGrid({ fields, onSaved, editMode }: { fields: FieldDef[]; onSaved?: () => void; editMode?: boolean }) {
  return (
    <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
      {fields.map((def) => {
        const [label, value] = def
        const editConfig = def.length === 3 ? def[2] : undefined
        return (
          <div key={label as string} className="flex flex-col py-1">
            <dt className="text-xs text-slate-400">{label as string}</dt>
            <dd className="text-sm text-slate-900">
              {editConfig && editMode ? (
                <EditableCell
                  value={editConfig.selectValue !== undefined ? editConfig.selectValue : value}
                  fieldKey={editConfig.fieldKey}
                  entity={editConfig.entity}
                  entityId={editConfig.entityId}
                  projectId={editConfig.projectId}
                  type={editConfig.type}
                  options={editConfig.options}
                  scaleOnSave={editConfig.scaleOnSave}
                  editMode={true}
                  onSaved={onSaved}
                />
              ) : value != null && String(value).startsWith('http') ? (
                <a href={String(value)} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline break-all">
                  {String(value)}
                </a>
              ) : (
                str(value)
              )}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}
