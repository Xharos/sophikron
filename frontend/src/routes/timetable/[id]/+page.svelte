<script lang="ts">
	import { untrack, tick } from 'svelte';
	import { SvelteDate, SvelteMap } from 'svelte/reactivity';
	import { resolve } from '$app/paths';
	import { invalidateAll } from '$app/navigation';
	import Modal from '#lib/components/Modal.svelte';
	import TimetableTree from '#lib/components/TimetableTree.svelte';
	import TimetableGrid from '#lib/components/TimetableGrid.svelte';
	import TimetableBlockEditor from '#lib/components/TimetableBlockEditor.svelte';
	import TimetableHours from '#lib/components/TimetableHours.svelte';
	import TimetableChoice from '#lib/components/TimetableChoice.svelte';
	import TimetableWarningEvents from '#lib/components/TimetableWarningEvents.svelte';
	import {
		warningEventTarget,
		uniqueWarningTargets,
		type WarningEventTarget
	} from '#lib/timetableWarnings';
	import { timetableCommand } from '#lib/timetableClient';
	import {
		blockKinds,
		isoWeek,
		mondayOf,
		nodeReceives,
		shiftTimetableDate,
		timetableTree,
		weeklyEvents,
		weeklySignature,
		weeklyIssues,
		timetableConflictDetails,
		previewTemplateEvents,
		teacherAvailabilityDetails,
		crossCalendarTeacherConflicts,
		datedBlockEvents,
		type TimetableWarning,
		type TimetableBlock,
		type TimetableBoard,
		type TimetableEvent,
		type TimetableNode,
		type TimetableIssue,
		type WeeklyBlock,
		type WeeklyTemplate
	} from '#lib/timetable';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let board = $state<TimetableBoard>({
		years: [],
		events: [],
		members: [],
		groups: [],
		warnings: []
	});
	let yearNumber = $state(0);
	let date = $state('');
	let initialized = $state(0);
	let selectedKey = $state('promotion');
	let treeOpen = $state(false);
	let templateMode = $state(false);
	let weeklyBlocks = $state<WeeklyBlock[]>([]);
	let versions = $state<WeeklyTemplate['versions']>([]);
	let effectiveOn = $state('');
	let scheduledVersion = $state(false);
	let activationOpen = $state(false);
	let acknowledgeHistory = $state(false);
	let activationNow = $state(0);
	let templateRevision = $state<string | null>(null);
	let clipboard = $state<{ block: TimetableBlock; phase: number } | null>(null);
	let savedPattern = $state('');
	let weeklyBufferYear = $state<number | null>(null);
	let loading = $state(false);
	let busy = $state(false);
	let message = $state('');
	let notice = $state('');
	let publishedView = $state(false);
	let warningsOpen = $state(false);
	let hoursOpen = $state(false);
	let versionsOpen = $state(false);
	let editorOpen = $state(false);
	let detail = $state<TimetableEvent | null>(null);
	let activeEvent = $state<TimetableEvent | null>(null);
	let editorMessage = $state('');
	let editorWeekday = $state(0);
	let phase = $state(1);
	let scope = $state<'one' | 'future'>('one');
	let occurrenceConfirmation = $state<{
		event: TimetableEvent;
		replacement: TimetableBlock | null;
		resized: boolean;
		yearId: number;
		revision: string | null;
		conflicts: TimetableWarning[];
	} | null>(null);
	let teacherConfirmation = $state<{
		warnings: TimetableWarning[];
		proceed: () => void | Promise<void>;
		editor: boolean;
		activation: boolean;
	} | null>(null);
	let confirmationMessage = $state('');
	let block = $state<TimetableBlock>({
		starts_on: '',
		start_slot: 0,
		duration_slots: 2,
		subject_id: null,
		teacher_id: null,
		room_id: null,
		kind: 'course',
		title: '',
		interval: 0,
		until: null
	});
	let requestNumber = 0;
	const administrator = $derived(data.catalog.administrator);
	const agenda = $derived({
		...data.agenda,
		...board.calendars?.find((item) => item.id === data.agenda.id)
	});
	const activeYear = $derived(board.years[0]);
	const retroactive = $derived(scheduledVersion && Date.parse(effectiveOn) < activationNow);
	const canPaste = $derived(
		!!clipboard &&
			(!templateMode ||
				(clipboard.block.kind !== 'kholle' &&
					['promotion', 'halves', 'thirds'].includes(clipboard.block.target_kind ?? 'promotion')))
	);
	const templateChanged = $derived(weeklySignature(weeklyBlocks) !== savedPattern);
	const summaryBlocks = $derived(templateMode ? weeklyBlocks : (activeYear?.template_blocks ?? []));
	const issues = $derived.by(() => {
		const values = new SvelteMap<string, TimetableIssue>(
			(board.issues ?? [])
				.filter((issue) => !issue.code.startsWith('promotion-'))
				.map((issue) => [issue.code, issue])
		);
		if (agenda.promotion_id === null)
			values.set(`promotion-${data.agenda.id}`, {
				code: `promotion-${data.agenda.id}`,
				severity: 'critical',
				message:
					'Aucune promotion affectée. Vous pouvez préparer et sauvegarder cet agenda, puis lui affecter une promotion pour le diffuser.'
			});
		if (activeYear)
			for (const issue of weeklyIssues(
				summaryBlocks,
				activeYear.settings.session_minutes,
				agenda.promotion_id,
				board.groups ?? [],
				data.catalog.subjects
			))
				values.set(issue.code, issue);
		if (administrator)
			for (const item of summaryBlocks) {
				if (
					item.teacher_id !== null &&
					!data.catalog.teachers.some((teacher) => teacher.id === item.teacher_id)
				) {
					const name =
						board.events.find((event) => event.teacher_id === item.teacher_id)?.teacher ??
						'Un enseignant indisponible';
					values.set(`teacher-${item.teacher_id}`, {
						code: `teacher-${item.teacher_id}`,
						severity: 'warning',
						teacher_id: item.teacher_id,
						message: `${name} reste affecté à la semaine type. Choisissez son remplaçant pour les prochaines séances ; l’historique sera conservé.`
					});
				}
			}
		return [...values.values()];
	});
	const promotionName = $derived(
		data.catalog.promotions.find((item) => item.id === agenda.promotion_id)?.name ?? agenda.name
	);
	const root = $derived(
		timetableTree(promotionName, agenda.promotion_id ?? 0, board.members, board.groups ?? [])
	);
	function flatten(node: TimetableNode): TimetableNode[] {
		return [node, ...node.children.flatMap(flatten)];
	}
	const selected = $derived(flatten(root).find((node) => node.key === selectedKey) ?? root);
	const referenceMonday = $derived(
		activeYear ? mondayOf(activeYear.settings.start) : mondayOf(data.catalog.today)
	);
	const displayedEvents = $derived.by(() => {
		const events =
			templateMode && activeYear
				? weeklyEvents(weeklyBlocks, activeYear, referenceMonday, agenda.promotion_id).map(
						(event) => {
							const source = weeklyBlocks.find((item) => item.key === event.series_id);
							const subject = data.catalog.subjects.find((item) => item.id === event.subject_id);
							const cycle =
								source && source.interval > 1
									? ` · ${source.interval === 2 ? (source.phase === 1 ? 'A' : 'B') : `Cycle ${source.phase}/3`}`
									: '';
							return {
								...event,
								title: (event.title || subject?.name || 'Séance') + cycle,
								color: subject?.color ?? '#64748B',
								teacher:
									data.catalog.teachers.find((item) => item.id === event.teacher_id)?.name ??
									board.events.find((item) => item.teacher_id === event.teacher_id)?.teacher ??
									'',
								teacher_roles:
									data.catalog.teachers.find((item) => item.id === event.teacher_id)?.roles ??
									board.events.find((item) => item.teacher_id === event.teacher_id)
										?.teacher_roles ??
									[],
								room: data.catalog.rooms.find((item) => item.id === event.room_id)?.name ?? ''
							};
						}
					)
				: board.events;
		return templateMode
			? events
			: events.filter((event) => nodeReceives(event, selected, board.members));
	});
	const conflictEvents = $derived(
		templateMode && activeYear
			? previewTemplateEvents(
					displayedEvents,
					weeklyBlocks,
					activeYear,
					data.catalog.today,
					board.events
				)
			: board.events
	);
	const warnings = $derived<TimetableWarning[]>([
		...board.warnings
			.filter(
				(warning) => !warning.startsWith('Conflit de ') && !warning.startsWith('Disponibilité de ')
			)
			.map((warning, index) => ({
				code: `other-${index}`,
				message: warning,
				summary: warning,
				events: [] as TimetableEvent[]
			})),
		...timetableConflictDetails(conflictEvents, board.groups ?? [], data.catalog.today),
		...crossCalendarTeacherConflicts(
			conflictEvents,
			board.teacher_commitments ?? [],
			data.catalog.today
		),
		...teacherAvailabilityDetails(
			conflictEvents,
			board.availability ?? [],
			data.catalog.today,
			activeYear?.school_year
		)
	]);
	function warningTargets(events: TimetableEvent[]): WarningEventTarget[] {
		if (!activeYear) return [];
		return uniqueWarningTargets(
			events.map((event) => warningEventTarget(event, activeYear, summaryBlocks, templateMode))
		);
	}
	function issueTargets(issue: TimetableIssue): WarningEventTarget[] {
		if (!activeYear) return [];
		if (issue.template_keys?.length) {
			const events = weeklyEvents(
				summaryBlocks.filter((block) => issue.template_keys?.includes(block.key)),
				activeYear,
				referenceMonday,
				agenda.promotion_id
			).map((event) => ({
				...event,
				template_key: event.series_id,
				teacher_roles:
					data.catalog.teachers.find((item) => item.id === event.teacher_id)?.roles ??
					board.events.find((item) => item.teacher_id === event.teacher_id)?.teacher_roles ??
					[],
				title:
					event.title ||
					data.catalog.subjects.find((item) => item.id === event.subject_id)?.name ||
					'Séance',
				teacher:
					data.catalog.teachers.find((item) => item.id === event.teacher_id)?.name ??
					board.events.find((item) => item.teacher_id === event.teacher_id)?.teacher ??
					''
			}));
			return uniqueWarningTargets(events.map((event) => ({ event, templateKey: event.series_id })));
		}
		if (issue.teacher_id !== undefined)
			return warningTargets(
				(templateMode ? displayedEvents : board.events).filter(
					(event) =>
						event.teacher_id === issue.teacher_id &&
						(templateMode || event.start.slice(0, 10) >= data.catalog.today)
				)
			);
		return [];
	}
	async function openWarningEvent(target: WarningEventTarget): Promise<void> {
		if (busy || loading || !activeYear) return;
		warningsOpen = false;
		await tick();
		if (!administrator) {
			date = target.event.start.slice(0, 10);
			detail = target.event;
			return;
		}
		if (publishedView) {
			publishedView = false;
			await tick();
			await refresh(data.agenda.id, yearNumber, false);
			if (!activeYear) return;
		}
		if (target.templateKey) {
			if (!templateMode) await beginTemplate();
			if (!templateMode || !activeYear) return;
			const block = weeklyBlocks.find((item) => item.key === target.templateKey);
			const event = block
				? weeklyEvents([block], activeYear, referenceMonday, agenda.promotion_id)[0]
				: null;
			if (!event) {
				message =
					'Ce bloc n’existe plus dans la semaine type actuelle. Actualisez les points à vérifier.';
				return;
			}
			await tick();
			edit(event);
		} else {
			templateMode = false;
			selectedKey = 'promotion';
			date = target.event.start.slice(0, 10);
			await tick();
			const event = board.events.find(
				(item) =>
					item.series_id === target.event.series_id && item.source_date === target.event.source_date
			);
			if (event) edit(event);
			else
				message =
					'Cette occurrence n’existe plus dans la préparation actuelle. Actualisez les points à vérifier.';
		}
	}
	const warningCount = $derived(issues.length + warnings.length);
	const week = $derived(date ? mondayOf(date) : '');
	const weekNumber = $derived(activeYear?.weeks[week]);
	$effect(() => {
		if (initialized !== data.agenda.id) {
			initialized = data.agenda.id;
			const current = data.catalog.common_years?.find(
				(item) =>
					item.settings &&
					item.settings.start <= data.catalog.today &&
					item.settings.end >= data.catalog.today
			);
			yearNumber =
				current?.school_year ??
				data.agenda.years[0]?.school_year ??
				Number(data.catalog.today.slice(0, 4)) -
					(Number(data.catalog.today.slice(5, 7)) < 9 ? 1 : 0);
			date = data.catalog.today;
			selectedKey = 'promotion';
			templateMode = false;
			clipboard = null;
		}
	});
	$effect(() => {
		const id = data.agenda.id;
		const year = yearNumber;
		const published = publishedView;
		if (year) void untrack(() => refresh(id, year, published));
	});
	async function refresh(
		id = data.agenda.id,
		year = yearNumber,
		published = publishedView
	): Promise<void> {
		const request = ++requestNumber;
		loading = true;
		message = '';
		try {
			const query = new URLSearchParams({
				calendar_ids: String(id),
				school_year: String(year),
				draft: String(administrator && !published)
			});
			const response = await fetch(`${resolve('/timetable/data')}?${query}`);
			const result = (await response.json()) as TimetableBoard & { message?: string };
			if (request !== requestNumber) return;
			if (!response.ok) throw new Error(result.message ?? 'Chargement impossible.');
			board = result;
			if (
				board.years[0] &&
				(date < board.years[0].settings.start || date > board.years[0].settings.end)
			)
				date = board.years[0].settings.start;
		} catch (cause) {
			if (request === requestNumber) {
				message = cause instanceof Error ? cause.message : 'Erreur de connexion.';
				board = { years: [], events: [], members: [], groups: [], warnings: [] };
			}
		} finally {
			if (request === requestNumber) loading = false;
		}
	}
	async function prepare(): Promise<void> {
		const shared = data.catalog.common_years?.find((item) => item.school_year === yearNumber);
		if (!shared?.settings) {
			message = 'Configurez d’abord les réglages communs de cette année scolaire.';
			return;
		}
		busy = true;
		try {
			await timetableCommand(`calendars/${data.agenda.id}/years`, 'POST', {
				settings: shared.settings,
				copy_previous: true
			});
			await refresh();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Préparation impossible.';
		} finally {
			busy = false;
		}
	}
	async function beginTemplate(): Promise<void> {
		if (!activeYear) return;
		if (weeklyBufferYear === activeYear.id && savedPattern && templateChanged) {
			templateMode = true;
			return;
		}
		busy = true;
		message = '';
		try {
			const response = await fetch(`${resolve('/timetable/template')}?year=${activeYear.id}`);
			const result = (await response.json()) as WeeklyTemplate & { message?: string };
			if (!response.ok) throw new Error(result.message ?? 'Semaine type indisponible.');
			weeklyBlocks = result.blocks;
			weeklyBufferYear = activeYear.id;
			savedPattern = weeklySignature(result.blocks);
			versions = result.versions;
			templateRevision = result.revision;
			treeOpen = false;
			templateMode = true;
			notice = '';
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Chargement impossible.';
		} finally {
			busy = false;
		}
	}
	async function synchronize(): Promise<void> {
		if (
			busy ||
			loading ||
			editorOpen ||
			activationOpen ||
			occurrenceConfirmation ||
			teacherConfirmation
		)
			return;
		try {
			await invalidateAll();
		} catch {
			message = 'Actualisation impossible. Réessayez dans un instant.';
		}
	}
	function leaveTemplate(): void {
		if (!templateChanged) {
			templateMode = false;
			notice = 'Aucun changement à enregistrer';
			return;
		}
		const local = new SvelteDate();
		local.setMinutes(local.getMinutes() - local.getTimezoneOffset());
		effectiveOn =
			activeYear && activeYear.settings.start > data.catalog.today
				? `${activeYear.settings.start}T00:00`
				: local.toISOString().slice(0, 16);
		scheduledVersion = false;
		acknowledgeHistory = false;
		activationNow = Date.now();
		message = '';
		activationOpen = true;
	}
	async function persistTemplate(
		blocks: WeeklyBlock[],
		activation: { effective_at?: string; acknowledge_history?: boolean } = {}
	): Promise<{
		revision: string;
		number?: number | null;
		changed?: boolean;
		effective_at?: string;
	}> {
		if (!activeYear) throw new Error('Année scolaire indisponible.');
		const response = await fetch(resolve('/timetable/template'), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				year_id: activeYear.id,
				data: { expected_revision: templateRevision, ...activation, blocks }
			})
		});
		const result = (await response.json()) as {
			revision: string;
			number?: number | null;
			changed?: boolean;
			message?: string;
			effective_at?: string;
		};
		if (!response.ok) throw new Error(result.message ?? 'Enregistrement impossible.');
		return result;
	}
	async function saveTemplate(confirmed = false): Promise<void> {
		if (!activeYear || busy) return;
		if (!templateChanged) {
			templateMode = false;
			notice = 'Aucun changement à enregistrer';
			return;
		}
		if (scheduledVersion && !Number.isFinite(Date.parse(effectiveOn))) {
			message = 'Choisissez une date et une heure d’application valides.';
			return;
		}
		activationNow = Date.now();
		if (retroactive && !acknowledgeHistory) {
			message = 'Confirmez le remplacement des séances passées pour appliquer cette date.';
			return;
		}
		if (
			!confirmed &&
			weeklyBlocks.some((item) => item.teacher_id !== null) &&
			!(await refreshTeacherCommitments())
		)
			return;
		const previewDate =
			scheduledVersion && effectiveOn.slice(0, 10) > data.catalog.today
				? effectiveOn.slice(0, 10)
				: data.catalog.today;
		if (
			!confirmed &&
			askTeacherConfirmation(
				previewTemplateEvents(displayedEvents, weeklyBlocks, activeYear, previewDate, []),
				() => saveTemplate(true)
			)
		)
			return;
		busy = true;
		message = '';
		try {
			const result = await persistTemplate(weeklyBlocks, {
				...(scheduledVersion ? { effective_at: new Date(effectiveOn).toISOString() } : {}),
				acknowledge_history: scheduledVersion && acknowledgeHistory
			});
			savedPattern = weeklySignature(weeklyBlocks);
			activationOpen = false;
			templateMode = false;
			date =
				result.effective_at?.slice(0, 10) ??
				(scheduledVersion ? effectiveOn.slice(0, 10) : data.catalog.today);
			await refresh();
			notice =
				result.changed === false
					? 'Aucun changement à enregistrer'
					: `Version ${result.number} enregistrée`;
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	function select(node: TimetableNode): void {
		selectedKey = node.key;
		treeOpen = false;
	}
	function create(day: string, slot: number): void {
		if (!administrator || publishedView || !activeYear) return;
		activeEvent = null;
		editorMessage = '';
		scope = 'one';
		editorWeekday = (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;
		phase = 1;
		block = {
			starts_on: day,
			start_slot: slot,
			duration_slots: Math.min(2, activeYear.slots.length - slot),
			subject_id: null,
			teacher_id: null,
			room_id: null,
			kind: 'course',
			title: '',
			interval: templateMode ? 1 : 0,
			until: activeYear.settings.end,
			target_kind:
				!templateMode && ['halves', 'thirds', 'kholles'].includes(selected.kind)
					? selected.kind
					: 'promotion',
			target_number:
				!templateMode && ['halves', 'thirds', 'kholles'].includes(selected.kind)
					? (selected.number ?? null)
					: null,
			target_user_id: null
		};
		editorOpen = true;
	}
	function chooseKind(kind: TimetableBlock['kind']): void {
		block.kind = kind;
	}
	function eventFields(event: TimetableEvent): TimetableBlock {
		const weekly = templateMode ? weeklyBlocks.find((item) => item.key === event.series_id) : null;
		const source = activeYear?.series.find((item) => item.id === event.series_id);
		return {
			starts_on: event.start.slice(0, 10),
			start_slot: event.start_slot,
			duration_slots: event.duration_slots,
			subject_id: event.subject_id,
			teacher_id: event.teacher_id,
			room_id: event.room_id,
			kind: event.kind,
			title:
				weekly?.title ??
				source?.exceptions[event.source_date]?.title ??
				source?.title ??
				event.title,
			interval: weekly?.interval ?? source?.interval ?? 0,
			until: source?.until ?? activeYear?.settings.end ?? null,
			target_kind: event.target_kind ?? 'promotion',
			target_number: event.target_number ?? null,
			target_user_id: event.target_user_id ?? null
		};
	}
	/** Template-derived occurrences always remain isolated from their recurring source. */
	function templateOccurrence(event: TimetableEvent): boolean {
		return !!(
			event.template_key ??
			activeYear?.series.find((item) => item.id === event.series_id)?.template_key
		);
	}
	function projectedWeeklyBlock(item: WeeklyBlock): TimetableEvent[] {
		if (!activeYear) return [];
		return previewTemplateEvents(
			weeklyEvents([item], activeYear, referenceMonday, agenda.promotion_id),
			[item],
			activeYear,
			data.catalog.today,
			[]
		);
	}
	function editedWeeklyBlock(): WeeklyBlock {
		const { starts_on, until, ...fields } = block;
		void starts_on;
		void until;
		return {
			...fields,
			key: activeEvent?.series_id ?? 'new-block',
			weekday: editorWeekday,
			interval: Math.max(1, block.interval) as 1 | 2 | 3,
			phase: Math.min(phase, Math.max(1, block.interval))
		};
	}
	function previewDatedBlock(
		fields: TimetableBlock,
		event: TimetableEvent | null
	): TimetableEvent[] {
		if (!activeYear) return [];
		return datedBlockEvents(
			{ ...fields, interval: event && scope === 'one' ? 0 : fields.interval },
			activeYear,
			agenda.promotion_id,
			event?.series_id ?? 'new-session'
		);
	}
	function teacherConflicts(events: TimetableEvent[]): TimetableWarning[] {
		return crossCalendarTeacherConflicts(
			events.map((event) => ({
				...event,
				teacher:
					event.teacher ||
					data.catalog.teachers.find((teacher) => teacher.id === event.teacher_id)?.name ||
					board.events.find((item) => item.teacher_id === event.teacher_id)?.teacher ||
					'Cet enseignant'
			})),
			board.teacher_commitments ?? [],
			data.catalog.today
		);
	}
	/** Re-read bookings before a write, including assignments made in another open calendar tab. */
	async function refreshTeacherCommitments(): Promise<boolean> {
		if (!activeYear) return false;
		const identifier = activeYear.id;
		busy = true;
		try {
			const query = new URLSearchParams({
				calendar_ids: String(agenda.id),
				school_year: String(yearNumber),
				draft: 'true'
			});
			const response = await fetch(`${resolve('/timetable/data')}?${query}`);
			const current = (await response.json()) as TimetableBoard & { message?: string };
			if (!response.ok)
				throw new Error(current.message ?? 'Vérification des engagements impossible.');
			if (activeYear?.id !== identifier)
				throw new Error('L’année affichée a changé. Recommencez votre modification.');
			board.teacher_commitments = current.teacher_commitments ?? [];
			return true;
		} catch (cause) {
			message = editorMessage =
				cause instanceof Error ? cause.message : 'Vérification des engagements impossible.';
			return false;
		} finally {
			busy = false;
		}
	}
	function askTeacherConfirmation(
		events: TimetableEvent[],
		proceed: () => void | Promise<void>
	): boolean {
		const warnings = teacherConflicts(events);
		if (!warnings.length) return false;
		teacherConfirmation = { warnings, proceed, editor: editorOpen, activation: activationOpen };
		editorOpen = activationOpen = false;
		return true;
	}
	function cancelTeacherConfirmation(): void {
		if (!teacherConfirmation || busy) return;
		editorOpen = teacherConfirmation.editor;
		activationOpen = teacherConfirmation.activation;
		teacherConfirmation = null;
	}
	async function acceptTeacherConfirmation(): Promise<void> {
		const pending = teacherConfirmation;
		if (!pending || busy) return;
		teacherConfirmation = null;
		editorOpen = pending.editor;
		activationOpen = pending.activation;
		await pending.proceed();
	}
	function requestOccurrenceChange(
		event: TimetableEvent,
		replacement: TimetableBlock | null,
		resized = false
	): void {
		if (!activeYear) return;
		occurrenceConfirmation = {
			event,
			replacement: replacement ? $state.snapshot(replacement) : null,
			resized,
			yearId: activeYear.id,
			revision: activeYear.revision,
			conflicts: replacement
				? teacherConflicts(previewDatedBlock({ ...replacement, interval: 0 }, event))
				: []
		};
		confirmationMessage = '';
		editorOpen = false;
	}
	function cancelOccurrenceChange(): void {
		if (busy) return;
		const reopenEditor = occurrenceConfirmation && !occurrenceConfirmation.resized;
		occurrenceConfirmation = null;
		if (reopenEditor) editorOpen = true;
	}
	async function confirmOccurrenceChange(): Promise<void> {
		const pending = occurrenceConfirmation;
		if (!pending || busy) return;
		busy = true;
		confirmationMessage = '';
		try {
			await timetableCommand(`years/${pending.yearId}/series/${pending.event.series_id}`, 'PUT', {
				expected_revision: pending.revision,
				occurrence: pending.event.source_date,
				scope: 'one',
				block: pending.replacement
			});
			occurrenceConfirmation = null;
			await refresh();
			notice = pending.resized
				? 'Redimensionnement enregistré en préparation'
				: 'Occurrence enregistrée en préparation';
		} catch (cause) {
			confirmationMessage = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	function edit(event: TimetableEvent): void {
		if (!administrator || publishedView) {
			detail = event;
			return;
		}
		activeEvent = event;
		editorMessage = '';
		scope = 'one';
		const weekly = templateMode ? weeklyBlocks.find((item) => item.key === event.series_id) : null;
		editorWeekday = weekly?.weekday ?? 0;
		phase = weekly?.phase ?? 1;
		block = eventFields(event);
		editorOpen = true;
	}
	function copy(event: TimetableEvent): void {
		if (!administrator || publishedView || busy) return;
		clipboard = {
			block: eventFields(event),
			phase: weeklyBlocks.find((item) => item.key === event.series_id)?.phase ?? 1
		};
		notice = 'Séance copiée. Collez-la à l’emplacement souhaité.';
	}
	function paste(day: string, slot: number): void {
		if (!clipboard || !canPaste || !administrator || publishedView || busy || !activeYear) return;
		create(day, slot);
		block = {
			...clipboard.block,
			starts_on: day,
			start_slot: slot,
			interval: templateMode ? (Math.max(1, clipboard.block.interval) as 1 | 2 | 3) : 0,
			until: templateMode ? activeYear.settings.end : null
		};
		phase = Math.min(clipboard.phase, Math.max(1, block.interval));
		if (slot + block.duration_slots > activeYear.slots.length)
			editorMessage =
				'La séance copiée dépasse la fin de journée. Réduisez sa longueur ou déplacez son début.';
	}
	async function move(
		event: TimetableEvent,
		day: string,
		slot: number,
		duration?: number,
		confirmed = false
	): Promise<void> {
		if (busy || teacherConfirmation || occurrenceConfirmation) return;
		if (templateMode) {
			if (!confirmed && event.teacher_id !== null && !(await refreshTeacherCommitments())) return;
			const source = weeklyBlocks.find((item) => item.key === event.series_id);
			const candidate = source
				? {
						...source,
						start_slot: slot,
						duration_slots: duration ?? source.duration_slots,
						weekday: (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7
					}
				: null;
			if (
				candidate &&
				!confirmed &&
				askTeacherConfirmation(projectedWeeklyBlock(candidate), () =>
					move(event, day, slot, duration, true)
				)
			)
				return;
			weeklyBlocks = weeklyBlocks.map((item) =>
				item.key === event.series_id
					? {
							...item,
							start_slot: slot,
							duration_slots: duration ?? item.duration_slots,
							weekday: (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7
						}
					: item
			);
		} else {
			edit(event);
			block.starts_on = day;
			block.start_slot = slot;
			if (duration) block.duration_slots = duration;
		}
	}
	async function resize(
		event: TimetableEvent,
		day: string,
		slot: number,
		duration: number,
		confirmed = false
	): Promise<void> {
		if (
			!administrator ||
			publishedView ||
			busy ||
			loading ||
			editorOpen ||
			occurrenceConfirmation ||
			teacherConfirmation ||
			!activeYear
		)
			return;
		if (slot === event.start_slot && duration === event.duration_slots) return;
		if (!confirmed && event.teacher_id !== null && !(await refreshTeacherCommitments())) return;
		if (templateMode) {
			const source = weeklyBlocks.find((item) => item.key === event.series_id);
			if (
				source &&
				!confirmed &&
				askTeacherConfirmation(
					projectedWeeklyBlock({ ...source, start_slot: slot, duration_slots: duration }),
					() => resize(event, day, slot, duration, true)
				)
			)
				return;
			weeklyBlocks = weeklyBlocks.map((item) =>
				item.key === event.series_id
					? { ...item, start_slot: slot, duration_slots: duration }
					: item
			);
			notice =
				'Redimensionnement conservé dans la semaine type en cours d’édition. Sauvegardez pour enregistrer la version.';
			return;
		}
		if (templateOccurrence(event)) {
			requestOccurrenceChange(
				event,
				{ ...eventFields(event), starts_on: day, start_slot: slot, duration_slots: duration },
				true
			);
			return;
		}
		if (
			!confirmed &&
			askTeacherConfirmation(
				previewDatedBlock(
					{
						...eventFields(event),
						starts_on: day,
						start_slot: slot,
						duration_slots: duration,
						interval: 0
					},
					event
				),
				() => resize(event, day, slot, duration, true)
			)
		)
			return;
		busy = true;
		message = '';
		notice = '';
		try {
			await timetableCommand(`years/${activeYear.id}/series/${event.series_id}`, 'PUT', {
				expected_revision: activeYear.revision,
				occurrence: event.source_date,
				scope: 'one',
				block: {
					...eventFields(event),
					starts_on: day,
					start_slot: slot,
					duration_slots: duration
				}
			});
			await refresh();
			notice = 'Redimensionnement enregistré en préparation';
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	async function saveBlock(remove = false, confirmed = false): Promise<void> {
		if (!activeYear || busy || teacherConfirmation || occurrenceConfirmation) return;
		if (!remove && block.subject_id === null && !block.title.trim()) {
			editorMessage =
				'Saisissez un intitulé personnalisé lorsqu’aucune matière n’est sélectionnée.';
			return;
		}
		if (!remove && block.start_slot + block.duration_slots > activeYear.slots.length) {
			editorMessage = 'Ce bloc dépasse la fin de journée.';
			return;
		}
		if (!remove && !confirmed && block.teacher_id !== null && !(await refreshTeacherCommitments()))
			return;
		if (templateMode) {
			if (
				!remove &&
				!confirmed &&
				askTeacherConfirmation(projectedWeeklyBlock(editedWeeklyBlock()), () =>
					saveBlock(remove, true)
				)
			)
				return;
			if (remove) weeklyBlocks = weeklyBlocks.filter((item) => item.key !== activeEvent?.series_id);
			else {
				const { starts_on: ignoredDate, until: ignoredUntil, ...fields } = block;
				void ignoredDate;
				void ignoredUntil;
				const updated: WeeklyBlock = {
					...fields,
					key: activeEvent?.series_id ?? crypto.randomUUID().replaceAll('-', ''),
					weekday: editorWeekday,
					interval: Math.max(1, block.interval) as 1 | 2 | 3,
					phase: Math.min(phase, Math.max(1, block.interval))
				};
				weeklyBlocks = [...weeklyBlocks.filter((item) => item.key !== updated.key), updated];
			}
			editorOpen = false;
			return;
		}
		if (activeEvent && templateOccurrence(activeEvent)) {
			requestOccurrenceChange(activeEvent, remove ? null : block);
			return;
		}
		if (
			!remove &&
			!confirmed &&
			askTeacherConfirmation(previewDatedBlock(block, activeEvent), () => saveBlock(remove, true))
		)
			return;
		busy = true;
		editorMessage = '';
		try {
			if (activeEvent)
				await timetableCommand(`years/${activeYear.id}/series/${activeEvent.series_id}`, 'PUT', {
					expected_revision: activeYear.revision,
					occurrence: activeEvent.source_date,
					scope,
					block: remove ? null : block
				});
			else
				await timetableCommand(`years/${activeYear.id}/series`, 'POST', {
					expected_revision: activeYear.revision,
					block
				});
			editorOpen = false;
			await refresh();
			notice = 'Séance enregistrée en préparation';
		} catch (cause) {
			editorMessage = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	async function publish(): Promise<void> {
		if (!activeYear) return;
		busy = true;
		message = '';
		try {
			await timetableCommand(`years/${activeYear.id}/publish`, 'POST', {
				expected_revision: activeYear.revision
			});
			await refresh();
			notice = 'Agenda publié';
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Publication impossible.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:window onfocus={() => void synchronize()} />

<svelte:head
	><title>{agenda.name} — {data.establishmentName}</title><meta
		name="description"
		content="Calendrier hebdomadaire de la promotion."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="calendar-workspace" aria-label={`Calendrier ${agenda.name}`}>
	<header class="workspace-toolbar">
		{#if !templateMode}<a class="back" href={resolve('/timetable')} aria-label="Retour aux agendas"
				>←</a
			>{/if}
		{#if !templateMode}<button
				class="tree-toggle"
				aria-label="Afficher les groupes"
				aria-expanded={treeOpen}
				onclick={() => (treeOpen = !treeOpen)}>☰</button
			>{/if}
		<div class="workspace-name">
			<h1>{agenda.name}</h1>
			<span>{templateMode ? 'Semaine type' : selected.label}</span>
		</div>
		{#if templateMode}
			<button class="button is-small is-light" disabled={busy} onclick={() => (versionsOpen = true)}
				>Versions ({versions.length})</button
			>
			<div class="toolbar-spacer"></div>
			<button class="button is-small is-primary" disabled={busy} onclick={leaveTemplate}
				>{templateChanged ? 'Sauvegarder' : 'Quitter'}</button
			>
		{:else}
			<div class="week-navigation">
				<button
					aria-label="Semaine précédente"
					disabled={busy || loading}
					onclick={() => (date = shiftTimetableDate(date, -7))}>‹</button
				><button class="today-button" onclick={() => (date = data.catalog.today)}
					>Aujourd’hui</button
				><button
					aria-label="Semaine suivante"
					disabled={busy || loading}
					onclick={() => (date = shiftTimetableDate(date, 7))}>›</button
				>
			</div>
			<label class="week-label"
				><span
					>{weekNumber ? `Semaine ${weekNumber}` : 'Hors cours'} (ISO {date
						? isoWeek(date)
						: ''})</span
				><input
					type="date"
					aria-label="Date affichée"
					bind:value={date}
					min={activeYear?.settings.start}
					max={activeYear?.settings.end}
				/></label
			>
			<div class="toolbar-spacer"></div>
			{#if administrator}
				{#if data.agenda.years.length > 1}<select
						class="year-select"
						aria-label="Année scolaire"
						bind:value={yearNumber}
						>{#each data.agenda.years as item (item.id)}<option value={item.school_year}
								>{item.school_year}–{item.school_year + 1}</option
							>{/each}</select
					>{/if}
				<button
					class="button is-small is-light"
					aria-pressed={publishedView}
					title={publishedView
						? 'Afficher la préparation modifiable'
						: 'Afficher la version actuellement diffusée aux abonnements ICS'}
					disabled={busy}
					onclick={() => (publishedView = !publishedView)}
					>{publishedView ? 'Version diffusée' : 'Préparation'}</button
				>
				<button
					class="button is-small is-light"
					disabled={busy || !activeYear || publishedView}
					onclick={beginTemplate}>Éditer la semaine type</button
				>
				<button
					class="button is-small is-primary"
					disabled={busy ||
						!activeYear ||
						agenda.is_paused ||
						publishedView ||
						activeYear.revision === activeYear.published_revision}
					onclick={publish}>{agenda.is_paused ? 'Diffusion figée' : 'Publier'}</button
				>
			{/if}
		{/if}
		{#if administrator && activeYear && !publishedView}<button
				class="button is-small is-light"
				aria-label="Ajouter une séance"
				title="Ajouter une séance"
				disabled={busy}
				onclick={() => create(templateMode ? referenceMonday : date, 0)}>+</button
			>{/if}
		<button
			class="warning-button"
			class:clear={warningCount === 0}
			class:critical={issues.some((issue) => issue.severity === 'critical') ||
				warnings.some((warning) => warning.severity === 'critical')}
			onclick={() => (warningsOpen = true)}
			aria-label={`Points à vérifier (${warningCount})`}>⚠ {warningCount}</button
		>
		{#if activeYear}<button
				class="button is-small is-light"
				aria-label="Heures par matière"
				onclick={() => (hoursOpen = true)}>▥ Heures</button
			>{/if}
	</header>
	{#if administrator && activeYear && !templateMode}<p class="publication-help">
			{publishedView
				? 'Cette version est celle reçue par les abonnements ICS.'
				: 'Préparation : vos changements sont enregistrés ici. « Publier » les diffuse aux abonnements ICS.'}
		</p>{/if}
	{#if message}<div class="workspace-message" role="alert">{message}</div>{/if}
	{#if notice}<span class="workspace-notice" role="status">{notice}</span>{/if}
	<div class="workspace-body">
		{#if !templateMode}<aside class="resource-sidebar" class:mobile-open={treeOpen}>
				<TimetableTree {root} selected={selected.key} onselect={select} />
			</aside>{/if}
		<div class="calendar-area" aria-busy={loading}>
			{#if loading}<div class="calendar-empty" role="status">Chargement…</div>
			{:else if activeYear}<TimetableGrid
					{templateMode}
					years={[activeYear]}
					events={displayedEvents}
					date={templateMode ? referenceMonday : date}
					editable={administrator && !publishedView && !busy}
					{canPaste}
					oncopy={copy}
					onpaste={paste}
					oncreate={create}
					onopen={edit}
					onmove={move}
					onresize={(event, day, slot, duration) => {
						void resize(event, day, slot, duration);
					}}
				/>
			{:else}<div class="calendar-empty">
					<h2>Aucune année scolaire disponible</h2>
					{#if administrator}<p>Les réglages de l’année sont communs à tous les agendas.</p>
						<div class="buttons mt-4">
							<button class="button is-primary" disabled={busy} onclick={prepare}
								>Préparer cet agenda</button
							><a class="button is-light" href={resolve('/timetable/settings')}>Réglages communs</a>
						</div>{:else}<p>Aucun emploi du temps publié pour l’année en cours.</p>{/if}
				</div>{/if}
		</div>
	</div>
</section>
{#if editorOpen && activeYear}<TimetableBlockEditor
		bind:block
		bind:weekday={editorWeekday}
		bind:phase
		bind:scope
		year={activeYear}
		catalog={data.catalog}
		groups={board.groups ?? []}
		promotionId={agenda.promotion_id}
		currentTeacherName={board.events.find((event) => event.teacher_id === block.teacher_id)
			?.teacher ?? ''}
		{templateMode}
		existing={!!activeEvent}
		occurrenceOnly={!templateMode && !!activeEvent && templateOccurrence(activeEvent)}
		{busy}
		message={editorMessage}
		onclose={() => (editorOpen = false)}
		onkindchange={chooseKind}
		onsave={() => saveBlock()}
		onremove={() => saveBlock(true)}
	/>{/if}
{#if teacherConfirmation}<Modal
		title="Enseignant déjà occupé"
		{busy}
		onclose={cancelTeacherConfirmation}
	>
		<p>
			Cette séance chevauche un engagement de l’enseignant dans un autre calendrier. Confirmez-vous
			l’enregistrement malgré cette incohérence ?
		</p>
		<ul class="notification is-danger is-light mt-4">
			{#each teacherConfirmation.warnings as warning (warning.code)}<li>
					{warning.summary}
				</li>{/each}
		</ul>
		<p class="help">Le conflit restera signalé en rouge dans les calendriers concernés.</p>
		<div class="dialog-actions">
			<button
				type="button"
				class="button is-light"
				disabled={busy}
				onclick={cancelTeacherConfirmation}>Annuler</button
			>
			<button
				type="button"
				class="button is-danger"
				disabled={busy}
				onclick={acceptTeacherConfirmation}>Confirmer malgré le conflit</button
			>
		</div>
	</Modal>{/if}
{#if occurrenceConfirmation}<Modal
		title={occurrenceConfirmation.replacement === null
			? 'Supprimer cette occurrence ?'
			: occurrenceConfirmation.resized
				? 'Redimensionner cette occurrence ?'
				: 'Modifier cette occurrence ?'}
		{busy}
		onclose={cancelOccurrenceChange}
	>
		<p>
			<strong>{occurrenceConfirmation.event.title}</strong> · {occurrenceConfirmation.event.start.slice(
				0,
				10
			)}
		</p>
		<p class="mt-3">
			Cette séance provient de la semaine type. Seule cette occurrence sera {occurrenceConfirmation.replacement ===
			null
				? 'supprimée'
				: 'modifiée'}. La semaine type et les autres occurrences seront conservées.
		</p>
		{#if occurrenceConfirmation.conflicts.length}<ul class="notification is-danger is-light mt-3">
				{#each occurrenceConfirmation.conflicts as warning (warning.code)}<li>
						{warning.summary}
					</li>{/each}
			</ul>
			<p class="help">
				Confirmer enregistrera aussi cette incohérence, qui restera signalée en rouge.
			</p>{/if}
		{#if confirmationMessage}<p class="notification is-danger is-light mt-3" role="alert">
				{confirmationMessage}
			</p>{/if}
		<div class="dialog-actions">
			<button type="button" class="button is-light" disabled={busy} onclick={cancelOccurrenceChange}
				>Annuler</button
			>
			<button
				type="button"
				class="button"
				class:is-danger={occurrenceConfirmation.replacement === null}
				class:is-primary={occurrenceConfirmation.replacement !== null}
				disabled={busy}
				onclick={confirmOccurrenceChange}>Confirmer</button
			>
		</div>
	</Modal>{/if}
{#if detail}<Modal title={detail.title} drawer onclose={() => (detail = null)}
		><p>{[blockKinds[detail.kind], detail.teacher].filter(Boolean).join(' · ')}</p>
		<p class="mt-3">
			{detail.start.slice(0, 10)} · {detail.start.slice(11, 19)}–{detail.end.slice(11, 19)}
		</p>
		{#if detail.room}<p class="mt-3">Salle {detail.room}</p>{/if}</Modal
	>{/if}
{#if warningsOpen}<Modal title="Points à vérifier" drawer onclose={() => (warningsOpen = false)}
		><ul class="warning-list">
			{#each issues as issue (issue.code)}<li class:critical-issue={issue.severity === 'critical'}>
					<strong>{issue.severity === 'critical' ? 'Critique' : 'Attention'}</strong> — {issue.teacher_id !==
					undefined
						? 'Un enseignant indisponible reste affecté à ces séances. Choisissez son remplaçant pour les prochaines séances ; l’historique sera conservé.'
						: issue.message}
					{#if activeYear}<TimetableWarningEvents
							targets={issueTargets(issue)}
							year={activeYear}
							catalog={data.catalog}
							onopen={(target) => {
								void openWarningEvent(target);
							}}
						/>{/if}
				</li>{/each}
			{#each warnings as warning (warning.code)}<li
					class:critical-issue={warning.severity === 'critical'}
				>
					{#if warning.severity === 'critical'}<strong>Critique</strong> —
					{/if}
					{warning.summary}
					{#if activeYear}<TimetableWarningEvents
							targets={warningTargets(warning.events)}
							year={activeYear}
							catalog={data.catalog}
							onopen={(target) => {
								void openWarningEvent(target);
							}}
						/>{/if}
				</li>{/each}
		</ul>
		{#if !warningCount}<p>Aucun point à vérifier.</p>{/if}
		<p class="help mt-4">Ces avertissements n’empêchent pas l’enregistrement.</p></Modal
	>{/if}
{#if hoursOpen && activeYear}<Modal
		title="Heures par matière"
		drawer
		onclose={() => (hoursOpen = false)}
		><TimetableHours
			blocks={summaryBlocks}
			sessionMinutes={activeYear.settings.session_minutes}
			subjects={data.catalog.subjects}
		/></Modal
	>{/if}
{#if versionsOpen}<Modal
		title="Versions de la semaine type"
		drawer
		onclose={() => (versionsOpen = false)}
		>{#each versions as version (version.number)}<p class="version-row">
				<strong>Version {version.number}</strong><span
					>À partir du {version.effective_at
						? new Date(version.effective_at).toLocaleString('fr-FR', {
								timeZone: 'Europe/Paris',
								dateStyle: 'short',
								timeStyle: 'short'
							})
						: version.effective_on} (Paris)</span
				>
			</p>{/each}{#if !versions.length}<p>
				La première version sera créée à l’enregistrement.
			</p>{/if}</Modal
	>{/if}

{#if activationOpen && activeYear}<Modal
		title="Appliquer les modifications"
		{busy}
		onclose={() => (activationOpen = false)}
	>
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void saveTemplate();
			}}
		>
			{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
			<TimetableChoice
				legend="Quand appliquer cette version ?"
				options={[
					{ value: 'now', label: 'Maintenant' },
					{ value: 'scheduled', label: 'À une autre date' }
				]}
				value={scheduledVersion ? 'scheduled' : 'now'}
				onchange={(value) => {
					scheduledVersion = value === 'scheduled';
					acknowledgeHistory = false;
					activationNow = Date.now();
				}}
				disabled={busy}
			/>
			{#if scheduledVersion}<div class="field">
					<label class="label" for="template-activation">Date et heure d’application</label><input
						id="template-activation"
						class="input"
						type="datetime-local"
						bind:value={effectiveOn}
						min={`${activeYear.settings.start}T00:00`}
						max={`${activeYear.settings.end}T23:59`}
						required
						onchange={() => {
							acknowledgeHistory = false;
							activationNow = Date.now();
						}}
					/>
					<p class="help">Heure de cet appareil.</p>
				</div>
			{:else}<p class="mb-4">
					La nouvelle version s’appliquera immédiatement, y compris aux séances en cours, ou à la
					rentrée pour une année future.
				</p>{/if}
			{#if retroactive}<div class="notification is-warning is-light" role="alert">
					<p>
						Cette date est passée. Les séances déjà survenues à partir de cet instant seront
						remplacées par la nouvelle version.
					</p>
					<label class="checkbox mt-3"
						><input type="checkbox" bind:checked={acknowledgeHistory} disabled={busy} /> Je confirme le
						remplacement des séances passées.</label
					>
				</div>{/if}
			<p class="help mb-4">
				Les abonnements ICS recevront ces changements lorsque vous cliquerez sur « Publier ».
			</p>
			<div class="buttons">
				<button class="button is-primary" disabled={busy || (retroactive && !acknowledgeHistory)}
					>Enregistrer la version</button
				><button
					type="button"
					class="button is-light"
					disabled={busy}
					onclick={() => (activationOpen = false)}>Revenir à l’édition</button
				>
			</div>
		</form>
	</Modal>{/if}

<style>
	.calendar-workspace {
		height: 100dvh;
		display: flex;
		flex-direction: column;
		background: var(--color-surface);
		overflow: hidden;
	}
	.workspace-toolbar {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		min-height: 65px;
		padding: 0.65rem 0.8rem;
		border-bottom: var(--border-thin);
		flex: none;
	}
	.back {
		color: var(--color-ink);
		font-size: 1.4rem;
		padding: 0.3rem;
	}
	.workspace-name {
		min-width: 130px;
		margin-right: 0.5rem;
	}
	h1 {
		font-size: 1rem;
		font-weight: 700;
		line-height: 1.3;
	}
	.workspace-name span {
		display: block;
		color: var(--color-muted);
		font-size: 0.73rem;
	}
	.toolbar-spacer {
		flex: 1;
	}
	.week-navigation {
		display: flex;
		gap: 3px;
	}
	.week-navigation button,
	.tree-toggle {
		border: 0;
		background: none;
		color: inherit;
		cursor: pointer;
		padding: 0.2rem 0.5rem;
		font-size: 1.3rem;
	}
	.week-navigation .today-button {
		font-size: 0.8rem;
	}
	.week-label {
		display: flex;
		flex-direction: column;
		font-size: 0.7rem;
		color: var(--color-muted);
	}
	.week-label input {
		width: 125px;
		font: inherit;
		color: var(--color-ink);
		border: 0;
		background: none;
	}
	.publication-help {
		padding: 0.35rem 0.8rem;
		color: var(--color-muted);
		background: var(--color-subtle);
		font-size: 0.75rem;
		border-bottom: var(--border-thin);
		flex: none;
	}
	.year-select {
		max-width: 120px;
		font-size: 0.8rem;
		border: var(--border-thin);
		color: inherit;
		background: var(--color-surface);
		border-radius: 5px;
		padding: 0.3rem;
	}
	.workspace-body {
		position: relative;
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.resource-sidebar {
		width: 245px;
		flex: none;
		border-right: var(--border-thin);
		display: flex;
		flex-direction: column;
		background: var(--color-surface);
		min-height: 0;
	}
	.calendar-area {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}
	.calendar-empty {
		display: flex;
		height: 100%;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 2rem;
		color: var(--color-muted);
		text-align: center;
	}
	.calendar-empty h2 {
		font-size: 1.2rem;
		color: var(--color-ink);
		margin-bottom: 0.5rem;
	}
	.workspace-message {
		padding: 0.55rem 1rem;
		color: var(--color-danger);
		background: var(--color-danger-soft);
		font-size: 0.85rem;
	}
	.workspace-notice {
		position: absolute;
		bottom: 16px;
		right: 24px;
		padding: 0.5rem 0.8rem;
		font-size: 0.8rem;
		background: var(--color-success-soft);
		color: var(--color-success);
		border-radius: 7px;
		z-index: 5;
		pointer-events: none;
	}
	.warning-button {
		border: 0;
		color: var(--color-warning);
		background: var(--color-warning-soft);
		border-radius: 6px;
		padding: 0.4rem;
		cursor: pointer;
	}
	.warning-list li {
		padding: 0.7rem 0;
		border-bottom: var(--border-thin);
	}
	.warning-button.clear {
		color: var(--color-success);
		background: var(--color-success-soft);
	}
	.warning-button.critical,
	.critical-issue {
		color: var(--color-danger);
		background: var(--color-danger-soft);
	}
	.warning-list .critical-issue {
		padding-inline: 0.65rem;
		border-radius: 6px;
	}
	.version-row {
		display: flex;
		flex-direction: column;
		padding: 0.8rem 0;
		border-bottom: var(--border-thin);
	}
	.version-row span {
		font-size: 0.8rem;
		color: var(--color-muted);
	}
	.tree-toggle {
		display: none;
	}
	@media (max-width: 1100px) {
		.workspace-toolbar {
			flex-wrap: wrap;
			gap: 0.4rem;
		}
		.resource-sidebar {
			width: 210px;
		}
	}
	@media (max-width: 760px) {
		.tree-toggle {
			display: block;
		}
		.resource-sidebar {
			display: none;
		}
		.resource-sidebar.mobile-open {
			display: flex;
			position: absolute;
			top: 0;
			bottom: 0;
			left: 0;
			width: 260px;
			z-index: 8;
			box-shadow: var(--shadow-panel);
		}
		.workspace-name {
			min-width: 100px;
		}
		.workspace-toolbar {
			min-height: 100px;
		}
		.workspace-toolbar :global(.button) {
			font-size: 0.7rem;
		}
		.toolbar-spacer {
			display: none;
		}
	}
</style>
