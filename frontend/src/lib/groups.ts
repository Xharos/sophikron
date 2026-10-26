/** Independent partition contracts shared by the board and its validation tests. */
export type PartitionKind = 'halves' | 'thirds' | 'kholles';
export type GroupAssignment = { promotion_id: number; kind: PartitionKind; number: number };
export type GroupStudent = { id: number; first_name: string; last_name: string };
export type GroupDraft = { number: number; x: number; y: number; student_ids: number[] };
export type Partition = {
	kind: PartitionKind;
	revision: string;
	target_size: number;
	groups: GroupDraft[];
};
export type PromotionGroupsData = { students: GroupStudent[]; partitions: Partition[] };

export const partitionLabels: Record<PartitionKind, string> = {
	halves: 'Demi-groupes',
	thirds: 'Tiers de groupe',
	kholles: 'Groupes de khôlle'
};

/** Keep the same names across previews, saved partitions and staff consultation. */
export function groupLabel(kind: PartitionKind, number: number): string {
	return `Groupe ${groupIdentifier(kind, number)}`;
}

/** Compact identifiers remain consistent across rosters, popup cards and full profiles. */
export function groupIdentifier(kind: PartitionKind, number: number): string {
	return kind === 'kholles' ? String(number).padStart(2, '0') : String.fromCharCode(64 + number);
}

/** Transfers permit temporary imbalance; persistence performs the final validation. */
export function moveStudent(groups: GroupDraft[], studentId: number, target: number): GroupDraft[] {
	if (!groups.some((group) => group.number === target)) return groups;
	return groups.map((group) => ({
		...group,
		student_ids: [
			...group.student_ids.filter((id) => id !== studentId),
			...(group.number === target ? [studentId] : [])
		]
	}));
}

/** Give immediate feedback while the backend remains authoritative. */
export function groupError(
	kind: PartitionKind,
	groups: GroupDraft[],
	rosterIds: number[],
	targetSize = 3
): string {
	if (!groups.length) return 'Générez une répartition pour commencer.';
	const assigned = groups.flatMap((group) => group.student_ids);
	const roster = new Set(rosterIds);
	if (
		assigned.length !== roster.size ||
		new Set(assigned).size !== roster.size ||
		assigned.some((id) => !roster.has(id))
	)
		return 'Affectez chaque élève à un seul groupe.';
	if ((kind === 'halves' && groups.length !== 2) || (kind === 'thirds' && groups.length !== 3))
		return 'Le nombre de groupes est invalide.';
	const sizes = groups.map((group) => group.student_ids.length);
	if (kind === 'kholles') {
		const remainder = roster.size % targetSize;
		const smaller = sizes.filter((size) => size !== targetSize);
		const valid =
			sizes.length === Math.ceil(roster.size / targetSize) &&
			(remainder === 0 ? smaller.length === 0 : smaller.length === 1 && smaller[0] === remainder);
		if (valid) return '';
		return `Chaque groupe de khôlle doit contenir ${targetSize} élèves${remainder ? `, sauf un seul groupe de ${remainder} élève(s) pour le reste` : ''}.`;
	}
	return Math.max(...sizes) - Math.min(...sizes) > 1
		? 'Équilibrez les groupes : un élève d’écart au maximum.'
		: '';
}
