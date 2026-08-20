// The filter tree decides what actually gets searched, so both helpers are
// worth pinning: a folder checkbox that grabs an unindexed file sends a
// dead slug to the backend, and a mis-nested archive tree hides documents
// the user paid to index.
import { describe, expect, it } from 'vitest'

import type { ArchiveApiResponse, LibraryFile, LibraryFolder } from '../types'
import { buildArchiveTree, collectReadySlugs } from './tree'

function file(name: string, status: LibraryFile['status']): LibraryFile {
  return { name, path: name, slug: `slug-${name}`, status, pinned: false }
}

function folder(
  name: string,
  files: LibraryFile[],
  folders: LibraryFolder[] = [],
): LibraryFolder {
  return { name, path: name, files, folders }
}

describe('collectReadySlugs', () => {
  it('takes indexed files only', () => {
    const tree = folder('lib', [
      file('ready.pdf', 'ready'),
      file('waiting.pdf', null),
      file('broken.pdf', 'failed'),
      file('running.pdf', 'processing'),
    ])

    expect(collectReadySlugs(tree)).toEqual(['slug-ready.pdf'])
  })

  it('reaches into subfolders', () => {
    const tree = folder('lib', [file('a.pdf', 'ready')], [
      folder('sub', [file('b.pdf', 'ready')], [folder('deep', [file('c.pdf', 'ready')])]),
    ])

    expect(collectReadySlugs(tree).sort()).toEqual([
      'slug-a.pdf',
      'slug-b.pdf',
      'slug-c.pdf',
    ])
  })
})

describe('buildArchiveTree', () => {
  const archive: ArchiveApiResponse = {
    paths: ['/projects/Most'],
    projects: [
      {
        name: 'Most',
        documents: [
          { slug: 'most__tz', project: 'Most', relative_path: 'TZ/tz.pdf', status: 'ready' },
          {
            slug: 'most__vykres',
            project: 'Most',
            relative_path: 'TZ/vykresy/v1.pdf',
            status: 'pending',
          },
        ],
      },
    ],
  }

  it('groups documents under their project folder, like the archive page', () => {
    // Two projects with root-level files used to merge into one flat list.
    const root = buildArchiveTree({
      paths: [],
      projects: [
        {
          name: 'P47',
          documents: [
            { slug: 'p47__a', project: 'P47', relative_path: 'a.pdf', status: 'ready' },
          ],
        },
        {
          name: 'Lavka',
          documents: [
            { slug: 'lavka__b', project: 'Lavka', relative_path: 'b.pdf', status: 'ready' },
          ],
        },
      ],
    })

    expect(root.files).toEqual([])
    expect(root.folders.map((f) => f.name)).toEqual(['P47', 'Lavka'])
    expect(root.folders[0].files[0].name).toEqual('a.pdf')
    expect(root.folders[1].files[0].name).toEqual('b.pdf')
  })

  it('nests by relative_path inside the project folder', () => {
    const root = buildArchiveTree(archive)

    const most = root.folders.find((f) => f.name === 'Most')!
    const tz = most.folders.find((f) => f.name === 'TZ')!
    expect(tz.files.map((f) => f.name)).toEqual(['tz.pdf'])
    expect(tz.folders.find((f) => f.name === 'vykresy')!.files[0].name).toEqual('v1.pdf')
  })

  it('marks only ready documents as searchable', () => {
    // pending/failed become null, so the filter cannot select them.
    expect(collectReadySlugs(buildArchiveTree(archive))).toEqual(['most__tz'])
  })

  it('understands Windows separators in old records', () => {
    const root = buildArchiveTree({
      paths: [],
      projects: [
        {
          name: 'Most',
          documents: [
            { slug: 's', project: 'Most', relative_path: 'TZ\\tz.pdf', status: 'ready' },
          ],
        },
      ],
    })

    const most = root.folders.find((f) => f.name === 'Most')!
    expect(most.folders[0].name).toEqual('TZ')
    expect(most.folders[0].files[0].name).toEqual('tz.pdf')
  })
})
