/** Independent partition contracts shared by the board and its validation tests. */
export type PartitionKind = 'halves' | 'thirds' | 'kholles';
export type GroupAssignment = { promotion_id: number; kind: PartitionKind; number: number };
export type GroupStudent = { id: number; first_name: string; last_name: string; status: string };
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
	return kind === 'kholles'
		? String(number).padStart(2, '0')
		: String.fromCharCode((kind === 'thirds' ? 87 : 64) + number);
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

/** Extract selected pupils into a new khôlle, retaining all other assignments and numbers. */
export function createKholleGroup(
	groups: GroupDraft[],
	studentIds: number[],
	x: number,
	y: number
): GroupDraft[] {
	const selected = new Set(studentIds);
	if (!selected.size || selected.size !== studentIds.length) return groups;
	const remaining = groups.flatMap((group) => {
		const members = group.student_ids.filter((id) => !selected.has(id));
		if (members.length === group.student_ids.length) return [group];
		return members.length ? [{ ...group, student_ids: members }] : [];
	});
	const used = new Set(remaining.map((group) => group.number));
	let number = 1;
	while (used.has(number)) number += 1;
	if (number > 1000) return groups;
	return [
		...remaining,
		{
			number,
			x: Math.round(Math.max(0, Math.min(1000000, x))),
			y: Math.round(Math.max(0, Math.min(1000000, y))),
			student_ids: [...studentIds]
		}
	].sort((left, right) => left.number - right.number);
}

/** Give immediate feedback while the backend remains authoritative. */
export function groupError(
	kind: PartitionKind,
	groups: GroupDraft[],
	rosterIds: number[],
	targetSize = 3,
	archivedIds: number[] = []
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
	const archived = new Set(archivedIds);
	const sizes = groups.map((group) => group.student_ids.filter((id) => !archived.has(id)).length);
	if (kind === 'kholles') {
		if (groups.some((group) => !group.student_ids.length))
			return 'Retirez les groupes de khôlle entièrement vides.';
		const activeCount = rosterIds.filter((id) => !archived.has(id)).length;
		const effectiveSizes = sizes.filter((size) => size > 0);
		const remainder = activeCount % targetSize;
		const smaller = effectiveSizes.filter((size) => size !== targetSize);
		const valid =
			effectiveSizes.length === Math.ceil(activeCount / targetSize) &&
			(remainder === 0 ? smaller.length === 0 : smaller.length === 1 && smaller[0] === remainder);
		if (valid) return '';
		return `Chaque groupe de khôlle doit contenir ${targetSize} élèves non archivés${remainder ? `, sauf un seul groupe de ${remainder} élève(s) pour le reste` : ''}.`;
	}
	return Math.max(...sizes) - Math.min(...sizes) > 1
		? 'Équilibrez les groupes : un élève d’écart au maximum.'
		: '';
}
