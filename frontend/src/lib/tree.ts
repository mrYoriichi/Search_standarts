// Tree helpers for the "where to search" filter.
import { t } from '../i18n'
import type { ArchiveApiResponse, LibraryFolder } from '../types'

/**
 * Slugs of all indexed (ready) PDFs in a folder, subfolders included.
 * Drives the "select the whole folder" checkbox and prunes a stale
 * selection — a slug that no longer exists makes the backend answer
 * "empty selection" instead of a result.
 */
export function collectReadySlugs(folder: LibraryFolder): string[] {
  const result: string[] = []
  for (const f of folder.files) {
    if (f.status === 'ready') result.push(f.slug)
  }
  for (const sub of folder.folders) {
    result.push(...collectReadySlugs(sub))
  }
  return result
}

/**
 * Turns the flat /api/projects response into a LibraryFolder-shaped tree
 * so FilterTree can render both pools unchanged. Nesting comes from
 * relative_path (project / section subfolders / file).
 */
export function buildArchiveTree(archive: ArchiveApiResponse): LibraryFolder {
  const root: LibraryFolder = {
    name: t('nav.archive'),
    path: '',
    folders: [],
    files: [],
  }

  function ensureFolder(
    parent: LibraryFolder,
    name: string,
    path: string,
  ): LibraryFolder {
    let folder = parent.folders.find((f) => f.name === name)
    if (!folder) {
      folder = { name, path, folders: [], files: [] }
      parent.folders.push(folder)
    }
    return folder
  }

  for (const project of archive.projects) {
    // Каждый проект — своя папка, как на странице архива; иначе файлы
    // из корней всех проектов ссыпаются в один плоский список.
    const projectFolder = ensureFolder(root, project.name, project.name)
    for (const doc of project.documents) {
      // Split on both separators: old Windows records contain `\`.
      const parts = doc.relative_path.split(/[\\/]/)
      let node = projectFolder
      let accPath = project.name
      for (const part of parts.slice(0, -1)) {
        accPath = `${accPath}/${part}`
        node = ensureFolder(node, part, accPath)
      }
      node.files.push({
        name: parts[parts.length - 1],
        path: doc.relative_path,
        slug: doc.slug,
        status:
          doc.status === 'ready'
            ? 'ready'
            : doc.status === 'processing'
              ? 'processing'
              : null,
        pinned: false,
      })
    }
  }
  return root
}
