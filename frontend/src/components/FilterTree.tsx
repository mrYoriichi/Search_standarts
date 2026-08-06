// The "where to search" tree: folders and indexed files with checkboxes.
import { collectReadySlugs } from '../lib/tree'
import type { LibraryFile, LibraryFolder } from '../types'

export function FilterTree({
  folder,
  selectedSlugs,
  searchAll,
  onToggleFile,
  onToggleFolder,
}: {
  folder: LibraryFolder
  selectedSlugs: Set<string>
  // With searchAll=true the tree checkboxes look checked and are disabled —
  // the user first unchecks "whole database", then fine-tunes the selection.
  searchAll: boolean
  onToggleFile: (slug: string) => void
  onToggleFolder: (folder: LibraryFolder) => void
}) {
  const readySlugs = collectReadySlugs(folder)
  // Hide folders without indexed files — otherwise lots of emptiness.
  if (readySlugs.length === 0) return null
  const allSelected = searchAll || readySlugs.every((s) => selectedSlugs.has(s))
  const readyFiles = folder.files.filter((f) => f.status === 'ready')

  return (
    <details className="text-sm">
      <summary className="cursor-pointer flex items-center gap-2">
        {/* A checkbox on every folder, root included — select/clear the pool. */}
        <input
          type="checkbox"
          checked={allSelected}
          disabled={searchAll}
          onChange={() => onToggleFolder(folder)}
          onClick={(e) => e.stopPropagation()}
          className="h-4 w-4"
        />
        <span className="font-medium">📁 {folder.name}</span>
      </summary>
      <div className="ml-5 mt-1 flex flex-col gap-1">
        {folder.folders.map((sub) => (
          <FilterTree
            key={sub.path}
            folder={sub}
            selectedSlugs={selectedSlugs}
            searchAll={searchAll}
            onToggleFile={onToggleFile}
            onToggleFolder={onToggleFolder}
          />
        ))}
        {readyFiles.map((file) => (
          <FileCheckbox
            key={file.path}
            file={file}
            selected={searchAll || selectedSlugs.has(file.slug)}
            disabled={searchAll}
            onToggle={onToggleFile}
          />
        ))}
      </div>
    </details>
  )
}

function FileCheckbox({
  file,
  selected,
  disabled,
  onToggle,
}: {
  file: LibraryFile
  selected: boolean
  disabled: boolean
  onToggle: (slug: string) => void
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-sm">
      <input
        type="checkbox"
        checked={selected}
        disabled={disabled}
        onChange={() => onToggle(file.slug)}
        className="h-4 w-4"
      />
      <span>📄 {file.name}</span>
    </label>
  )
}
