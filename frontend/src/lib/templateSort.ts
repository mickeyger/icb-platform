// WO v4.33.1 §3.6 — human-numeric template ordering (fixes the lexical "15.5m before 2.3m" bug).
//
// The size_category bucket drives the order: a numeric metre value sorts by its number
// ('2.3m' → 2.3, '15.5m' → 15.5); the named buckets 'mid' / 'big' slot BETWEEN the small and large
// numerics (so 2.3m < 3.2m < mid < big < 15.5m — §0.9's example); templates with no size_category
// (Bakery, Dry Freight, Explosive, Medical Waste) sort last. Within a bucket, alpha by name.
//
// Falls back to a leading metre value parsed from the NAME when size_category is absent, so a
// numbered name still sorts numerically even without the structured field.
export interface SortableTemplate {
  name: string
  size_category?: string | null
}

export function templateSizeRank(t: SortableTemplate): number {
  const sc = (t.size_category ?? '').toLowerCase()
  const scNum = parseFloat((sc.match(/(\d+(?:\.\d+)?)/) ?? [])[1] ?? 'NaN')
  if (!Number.isNaN(scNum)) return scNum         // '2.3m' → 2.3, '15.5m' → 15.5
  if (sc === 'mid') return 6                      // between the small numerics and 'big'
  if (sc === 'big') return 9                      // between 'mid' and the large numerics (15.5)
  const nameNum = parseFloat((t.name.match(/^\s*(\d+(?:\.\d+)?)\s*m/i) ?? [])[1] ?? 'NaN')
  return Number.isNaN(nameNum) ? Number.POSITIVE_INFINITY : nameNum
}

export function compareTemplatesBySize(a: SortableTemplate, b: SortableTemplate): number {
  return templateSizeRank(a) - templateSizeRank(b) || a.name.localeCompare(b.name)
}
