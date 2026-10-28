<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { Calendar, TimeGrid, Interaction } from '@event-calendar/core';
	import '@event-calendar/core/index.css';
	import {
		clockSeconds,
		blockKinds,
		timetableAudienceLabel,
		resizedTimetableSlots,
		timetableClock,
		mondayOf,
		shiftTimetableDate,
		type TimetableEvent,
		type TimetableYear,
		type AvailabilityRange
	} from '#lib/timetable';
	let {
		years,
		events,
		date,
		editable,
		oncreate,
		onopen,
		onmove,
		oncopy,
		onpaste,
		canPaste = false,
		templateMode = false,
		availabilityMode = false,
		occupiedRanges = [],
		onrangechange,
		onresize
	}: {
		years: TimetableYear[];
		events: TimetableEvent[];
		date: string;
		editable: boolean;
		oncreate: (date: string, slot: number) => void;
		onopen: (event: TimetableEvent) => void;
		onmove: (event: TimetableEvent, date: string, slot: number, duration?: number) => void;
		oncopy: (event: TimetableEvent) => void;
		onpaste: (date: string, slot: number) => void;
		canPaste?: boolean;
		templateMode?: boolean;
		availabilityMode?: boolean;
		occupiedRanges?: AvailabilityRange[];
		onrangechange?: (event: TimetableEvent, day: string, start: number, end: number) => void;
		onresize?: (event: TimetableEvent, day: string, slot: number, duration: number) => void;
	} = $props();
	let mounted = $state(false);
	let availableHeight = $state(0);
	let grid: HTMLDivElement;
	let menuElement = $state<HTMLDivElement>();
	let pointer = $state<{ day: string; slot: number; eventId: string | null } | null>(null);
	let menu = $state<{
		day: string;
		slot: number;
		eventId: string | null;
		x: number;
		y: number;
	} | null>(null);
	const instructionsId = $props.id();
	function pointAt(x: number, y: number, target: EventTarget | null): typeof pointer {
		const settings = years[0]?.settings;
		if (!settings || !grid) return null;
		const days = [...grid.querySelectorAll<HTMLElement>('.ec-body .ec-day')];
		const index = days.findIndex((day) => {
			const bounds = day.getBoundingClientRect();
			return x >= bounds.left && x < bounds.right && y >= bounds.top && y < bounds.bottom;
		});
		if (index < 0) return null;
		const bounds = days[index].getBoundingClientRect();
		const first = Math.floor(settings.day_start / 3600) * 3600;
		const last = Math.ceil(settings.day_end / 3600) * 3600;
		const seconds = first + ((y - bounds.top) / bounds.height) * (last - first);
		if (
			seconds < settings.day_start ||
			seconds >= settings.day_end ||
			settings.breaks.some((pause) => seconds >= pause.start && seconds < pause.end)
		)
			return null;
		return {
			day: shiftTimetableDate(mondayOf(date), index),
			slot: nearestSlot(seconds),
			eventId:
				target instanceof Element
					? (target.closest<HTMLElement>('[data-timetable-event-id]')?.dataset.timetableEventId ??
						null)
					: null
		};
	}
	async function openContext(x: number, y: number, target: EventTarget | null): Promise<void> {
		const point = pointAt(x, y, target);
		if (!editable || availabilityMode || !point) return;
		pointer = point;
		menu = {
			...point,
			x: Math.max(8, Math.min(x, window.innerWidth - 210)),
			y: Math.max(8, Math.min(y, window.innerHeight - 115))
		};
		await tick();
		menuElement?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
	}
	function copyHere(): void {
		const event = events.find((event) => event.id === menu?.eventId);
		if (event && editable) oncopy(event);
		menu = null;
		grid?.focus({ preventScroll: true });
	}
	function pasteHere(): void {
		if (menu && editable && canPaste) onpaste(menu.day, menu.slot);
		menu = null;
	}
	function keyboard(event: KeyboardEvent): void {
		if (
			!editable ||
			availabilityMode ||
			document.querySelector('dialog[open]') ||
			(event.target instanceof Element &&
				event.target.closest('input, textarea, select, [contenteditable="true"]'))
		)
			return;
		if (event.key === 'Escape' && menu) {
			event.preventDefault();
			menu = null;
			grid?.focus({ preventScroll: true });
			return;
		}
		if (menu && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
			event.preventDefault();
			const buttons = [
				...(menuElement?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
			];
			const current = buttons.findIndex((button) => button === document.activeElement);
			buttons[
				(current + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length
			]?.focus();
			return;
		}
		if (
			(event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) &&
			grid?.contains(document.activeElement)
		) {
			event.preventDefault();
			const target =
				document.activeElement?.closest('[data-timetable-event-id]') ??
				grid.querySelector('.ec-body .ec-day');
			const bounds = target?.getBoundingClientRect();
			if (bounds)
				void openContext(
					bounds.x + bounds.width / 2,
					bounds.y + Math.min(bounds.height / 2, 8),
					target
				);
			return;
		}
		if (
			!(event.ctrlKey || event.metaKey) ||
			event.altKey ||
			!pointer ||
			window.getSelection()?.toString()
		)
			return;
		if (event.key.toLowerCase() === 'c') {
			const selected = events.find((item) => item.id === pointer?.eventId);
			if (selected) {
				event.preventDefault();
				oncopy(selected);
			}
		} else if (event.key.toLowerCase() === 'v' && canPaste) {
			event.preventDefault();
			onpaste(pointer.day, pointer.slot);
			menu = null;
		}
	}
	$effect(() => {
		void date;
		void templateMode;
		pointer = null;
		menu = null;
	});
	onMount(() => {
		mounted = true;
	});
	function nearestSlot(seconds: number): number {
		let best = 0;
		for (let index = 1; index < (years[0]?.slots.length ?? 0); index++) {
			if (
				Math.abs(years[0].slots[index][0] - seconds) < Math.abs(years[0].slots[best][0] - seconds)
			)
				best = index;
		}
		return best;
	}
	const options = $derived.by((): Calendar.Options => {
		const displayed = events.map((event) => {
			const start = clockSeconds(event.start.slice(11, 19));
			const end = clockSeconds(event.end.slice(11, 19));
			return {
				id: event.id,
				start: event.start.slice(0, 19),
				end: event.end.slice(0, 19),
				backgroundColor: availabilityMode
					? `color-mix(in srgb, ${event.color} 80%, transparent)`
					: event.color,
				classNames: event.kind === 'kholle' ? ['timetable-kholle'] : [],
				styles: [`--timetable-event-color: ${event.color}`],
				extendedProps: { timetable: event },
				title: `${timetableClock(start).replace(/:00$/, '')}–${timetableClock(end).replace(/:00$/, '')} · ${event.title}${event.room || event.teacher ? `\n${[event.room, event.teacher].filter(Boolean).join(' · ')}` : ''}`
			};
		});
		const settings = years[0]?.settings;
		const pauses = settings
			? Array.from({ length: settings.saturday ? 6 : 5 }, (_, index) =>
					shiftTimetableDate(mondayOf(date), index)
				).flatMap((day) =>
					settings.breaks.map((pause, index) => ({
						id: `pause-${day}-${index}`,
						title: 'Pause',
						start: `${day}T${timetableClock(pause.start)}`,
						end: `${day}T${timetableClock(pause.end)}`,
						display: 'background' as const,
						backgroundColor: 'var(--color-border)',
						textColor: 'var(--color-ink)'
					}))
				)
			: [];
		const occupied = availabilityMode
			? occupiedRanges.map((range, index) => {
					const day = shiftTimetableDate(mondayOf(date), range.weekday);
					return {
						id: `occupied-${index}`,
						title: 'Tous les élèves occupés',
						start: `${day}T${timetableClock(range.start)}`,
						end: `${day}T${timetableClock(range.end)}`,
						display: 'background' as const,
						backgroundColor: 'transparent',
						classNames: ['timetable-occupied']
					};
				})
			: [];
		return {
			view: 'timeGridWeek',
			date,
			firstDay: 1,
			dayHeaderFormat: templateMode
				? { weekday: 'long' }
				: { weekday: 'short', day: 'numeric', month: 'short' },
			locale: 'fr-FR',
			allDaySlot: false,
			headerToolbar: { start: '', center: '', end: '' },
			hiddenDays: years.some((year) => year.settings.saturday) ? [0] : [0, 6],
			slotDuration: '01:00:00',
			slotLabelInterval: '01:00:00',
			slotMinTime: timetableClock(Math.floor((settings?.day_start ?? 28800) / 3600) * 3600),
			slotMaxTime: timetableClock(Math.ceil((settings?.day_end ?? 61200) / 3600) * 3600),
			snapDuration: { seconds: (settings?.session_minutes ?? 55) * 30 },
			slotHeight: Math.max(
				72,
				Math.floor(
					(availableHeight - 55) /
						(Math.ceil((settings?.day_end ?? 61200) / 3600) -
							Math.floor((settings?.day_start ?? 28800) / 3600))
				)
			),
			height: '100%',
			scrollTime: timetableClock(settings?.day_start ?? 28800),
			editable,
			eventResizableFromStart: true,
			slotEventOverlap: false,
			eventDidMount: (info) => {
				info.el.dataset.timetableEventId = String(info.event.id);
			},
			displayEventEnd: false,
			eventContent: (info) => {
				const title = document.createElement('div');
				title.className = 'ec-event-title';
				const event = info.event.extendedProps.timetable as TimetableEvent | undefined;
				if (event) {
					if (event.title.trim()) {
						const name = document.createElement('strong');
						name.className = 'timetable-event-name';
						name.textContent = event.title;
						title.append(name);
					}
					if (!availabilityMode) {
						if (event.calendar_label?.trim()) {
							const calendar = document.createElement('span');
							calendar.className = 'timetable-event-calendar';
							calendar.textContent = event.calendar_label;
							title.append(calendar);
						}
						const audience = document.createElement('span');
						audience.className = 'timetable-event-audience';
						audience.textContent = `${blockKinds[event.kind]} · ${timetableAudienceLabel(event)}`;
						title.append(audience);
					}
					if (event.teacher.trim()) {
						const teacher = document.createElement('em');
						teacher.className = 'timetable-event-teacher';
						teacher.textContent = event.teacher;
						title.append(teacher);
					}
					const details = document.createElement('span');
					details.className = 'timetable-event-details';
					const start = timetableClock(clockSeconds(event.start.slice(11, 19))).replace(/:00$/, '');
					const end = timetableClock(clockSeconds(event.end.slice(11, 19))).replace(/:00$/, '');
					details.textContent = [`${start}–${end}`, event.room.trim()].filter(Boolean).join(' · ');
					title.append(details);
				} else {
					title.textContent = typeof info.event.title === 'string' ? info.event.title : '';
				}
				return { domNodes: [title] };
			},
			slotLabelFormat: (value) => {
				return `${String(value.getHours()).padStart(2, '0')} h`;
			},
			events: [...displayed, ...pauses, ...occupied],
			dateClick: (info) => {
				if (!editable || !(info.jsEvent instanceof MouseEvent)) return;
				const bounds = info.dayEl.getBoundingClientRect();
				const first = Math.floor((settings?.day_start ?? 28800) / 3600) * 3600;
				const last = Math.ceil((settings?.day_end ?? 61200) / 3600) * 3600;
				const seconds =
					first + ((info.jsEvent.clientY - bounds.top) / bounds.height) * (last - first);
				if (settings && (seconds < settings.day_start || seconds >= settings.day_end)) return;
				if (settings?.breaks.some((pause) => pause.start <= seconds && seconds < pause.end)) return;
				oncreate(info.dateStr.slice(0, 10), nearestSlot(seconds));
			},
			eventClick: (info) => {
				const event = events.find((item) => item.id === String(info.event.id));
				if (event) onopen(event);
			},
			eventDrop: (info) => {
				const event = events.find((item) => item.id === String(info.event.id));
				const moved = new Date(info.event.start);
				const movedEnd = info.event.end;
				info.revert();
				if (!event || !info.event.start) return;
				if (availabilityMode && movedEnd) {
					rangeChanged(event, moved, movedEnd);
					return;
				}
				const seconds = moved.getHours() * 3600 + moved.getMinutes() * 60 + moved.getSeconds();
				const logical =
					(years[0]?.slots[event.start_slot]?.[0] ?? seconds) +
					seconds -
					clockSeconds(event.start.slice(11, 19));
				const day = `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, '0')}-${String(moved.getDate()).padStart(2, '0')}`;
				onmove(event, day, nearestSlot(logical));
			},
			eventResize: (info) => {
				const event = events.find((item) => item.id === String(info.event.id));
				const end = info.event.end;
				const start = info.event.start;
				info.revert();
				if (!event || !start || !end || !years[0]?.slots.length) return;
				if (availabilityMode && start) {
					rangeChanged(event, start, end);
					return;
				}
				const first = start.getHours() * 3600 + start.getMinutes() * 60 + start.getSeconds();
				const last =
					end.getHours() * 3600 +
					end.getMinutes() * 60 +
					end.getSeconds() +
					(end.getDate() !== start.getDate() ? 86400 : 0);
				const resized = resizedTimetableSlots(event, first, last, years[0].slots);
				(onresize ?? onmove)(
					event,
					event.start.slice(0, 10),
					resized.start_slot,
					resized.duration_slots
				);
			}
		};
	});
	function rangeChanged(event: TimetableEvent, start: Date, end: Date): void {
		const day = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
		const seconds = start.getHours() * 3600 + start.getMinutes() * 60 + start.getSeconds();
		onrangechange?.(event, day, seconds, seconds + (end.getTime() - start.getTime()) / 1000);
	}
</script>

<svelte:window
	onkeydown={keyboard}
	onpointerdown={(event) => {
		if (
			menu &&
			!(event.target instanceof Element && event.target.closest('.timetable-context-menu'))
		)
			menu = null;
	}}
	onresize={() => (menu = null)}
/>
<!-- svelte-ignore a11y_no_noninteractive_tabindex (The scrollable calendar region is a keyboard shortcut target.) -->
<div
	class="timetable-grid"
	bind:this={grid}
	bind:clientHeight={availableHeight}
	role="region"
	aria-label="Grille de l’emploi du temps"
	aria-describedby={instructionsId}
	tabindex="0"
	onpointermove={(event) => {
		if (!menu) pointer = pointAt(event.clientX, event.clientY, event.target);
	}}
	onpointerleave={() => {
		if (!menu) pointer = null;
	}}
	oncontextmenu={(event) => {
		if (editable && !availabilityMode && pointAt(event.clientX, event.clientY, event.target)) {
			event.preventDefault();
			void openContext(event.clientX, event.clientY, event.target);
		}
	}}
>
	{#if mounted && years[0]?.slots.length}<Calendar plugins={[TimeGrid, Interaction]} {options} />
	{:else}<p role="status" class="p-5">Préparation de la grille…</p>{/if}
</div>
<p id={instructionsId} class="is-sr-only">
	{#if availabilityMode}Déplacez une disponibilité ou redimensionnez ses bordures. Cliquez dessus
		pour modifier ses horaires au clavier ou la supprimer.
	{:else}
		Survolez une séance et utilisez Ctrl+C pour la copier, puis Ctrl+V à l’emplacement souhaité. Le
		clic droit propose les mêmes actions. Le formulaire permet de vérifier la copie avant de
		l’enregistrer.
	{/if}
</p>
{#if menu}<div
		bind:this={menuElement}
		class="timetable-context-menu"
		role="menu"
		aria-label="Copier ou coller une séance"
		style:left={`${menu.x}px`}
		style:top={`${menu.y}px`}
	>
		<button
			type="button"
			role="menuitem"
			disabled={!menu.eventId || !events.some((event) => event.id === menu?.eventId)}
			onclick={copyHere}>Copier la séance <kbd>Ctrl+C</kbd></button
		>
		<button type="button" role="menuitem" disabled={!canPaste} onclick={pasteHere}
			>Coller ici <kbd>Ctrl+V</kbd></button
		>
	</div>{/if}

<style>
	.timetable-context-menu {
		position: fixed;
		z-index: 30;
		width: 200px;
		border: var(--border-thin);
		border-radius: 8px;
		background: var(--color-surface);
		box-shadow: var(--shadow-panel);
		padding: 0.3rem;
	}
	.timetable-context-menu button {
		display: flex;
		justify-content: space-between;
		gap: 0.6rem;
		width: 100%;
		border: 0;
		border-radius: 4px;
		background: none;
		color: var(--color-ink);
		font: inherit;
		font-size: 0.8rem;
		text-align: left;
		padding: 0.7rem 0.5rem;
		cursor: pointer;
	}
	.timetable-context-menu button:hover,
	.timetable-context-menu button:focus-visible {
		background: var(--color-soft);
		outline: 2px solid var(--color-primary);
		outline-offset: -2px;
	}
	.timetable-context-menu button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	kbd {
		font: inherit;
		font-size: 0.68rem;
		color: var(--color-muted);
	}
	.timetable-grid {
		overflow-x: auto;
		height: 100%;
		min-height: 0;
	}
	.timetable-grid :global(.ec) {
		min-width: 720px;
		--ec-border-color: var(--color-border);
		--ec-bg-color: var(--color-surface);
		--ec-today-bg-color: var(--color-soft);
		--ec-event-col-gap: 0.75rem;
		font-family: inherit;
	}
	.timetable-grid :global(.ec-event-title) {
		position: static;
		text-align: left;
		white-space: pre-line;
		font-size: 0.78rem;
		line-height: 1.35;
		overflow: hidden;
		overflow-wrap: anywhere;
		text-overflow: ellipsis;
	}
	.timetable-grid :global(.ec-event-body) {
		justify-content: flex-start;
		align-items: stretch;
		min-width: 0;
		overflow: hidden;
	}
	.timetable-grid :global(.ec-time) {
		font-size: 0.72rem;
		min-width: 85px;
	}
	.timetable-grid :global(.ec-event) {
		border: 0;
		box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--timetable-event-color) 65%, black);
		border-radius: 7px;
		cursor: pointer;
		padding: 6px;
		overflow: hidden;
		min-width: 0;
	}
	.timetable-grid :global(.timetable-event-name),
	.timetable-grid :global(.timetable-event-calendar),
	.timetable-grid :global(.timetable-event-audience),
	.timetable-grid :global(.timetable-event-teacher),
	.timetable-grid :global(.timetable-event-details) {
		display: block;
		margin: 0;
	}
	.timetable-grid :global(.ec-event.timetable-kholle) {
		background-image: repeating-linear-gradient(
			135deg,
			transparent 0,
			transparent 14px,
			rgb(255 255 255 / 14%) 14px,
			rgb(255 255 255 / 14%) 15px
		);
	}
	.timetable-grid :global(.timetable-event-name) {
		color: inherit;
		font-weight: 700;
	}
	.timetable-grid :global(.timetable-event-teacher) {
		font-style: italic;
	}
	.timetable-grid :global(.timetable-event-details),
	.timetable-grid :global(.timetable-event-calendar),
	.timetable-grid :global(.timetable-event-audience) {
		font-size: 0.72rem;
	}
	.timetable-grid :global(.ec-header .ec-today) {
		color: var(--color-ink);
	}
	.timetable-grid :global(.ec-bg-event) {
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-ink);
		background-image: repeating-linear-gradient(
			135deg,
			transparent,
			transparent 5px,
			var(--color-muted) 5px,
			var(--color-muted) 6px
		);
	}
	.timetable-grid :global(.ec-bg-event .ec-event-body) {
		flex: initial;
		text-align: center;
	}
	.timetable-grid :global(.ec-bg-event.timetable-occupied) {
		opacity: 1;
		pointer-events: none;
		background-image: repeating-linear-gradient(
			45deg,
			transparent 0,
			transparent 10px,
			light-dark(rgb(148 163 184 / 80%), rgb(203 213 225 / 50%)) 10px,
			light-dark(rgb(148 163 184 / 80%), rgb(203 213 225 / 50%)) 13px
		);
	}
	.timetable-grid :global(.timetable-occupied .ec-event-title) {
		display: none;
	}
	.timetable-grid :global(.ec-bg-event .ec-event-title) {
		position: static;
		text-align: center;
		font-size: 0.7rem;
		font-weight: 600;
	}
	.timetable-grid :global(.ec-body .ec-day) {
		background-image:
			linear-gradient(to top, var(--color-border) 1px, transparent 1px),
			repeating-linear-gradient(
				to bottom,
				var(--color-surface) 0,
				var(--color-surface) var(--ec-slot-height),
				var(--color-subtle) var(--ec-slot-height),
				var(--color-subtle) calc(2 * var(--ec-slot-height))
			);
		background-size:
			100% var(--ec-slot-height),
			100% 100%;
	}
	.timetable-grid :global(.ec-body .ec-slot:first-child) {
		inset-block-start: 0;
		visibility: visible;
	}
</style>
