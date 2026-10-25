<script lang="ts">
	import {
		faChartPie,
		faLayerGroup,
		faUsers,
		faPlus,
		faPen,
		faBoxArchive,
		faRotateLeft,
		faMagnifyingGlass,
		faChevronLeft,
		faChevronRight,
		faXmark,
		faEnvelope,
		faLink,
		faCheck,
		faGraduationCap,
		faChalkboardUser,
		faArrowRight,
		faArrowUpRightFromSquare,
		faCakeCandles,
		faLocationDot,
		faPhone,
		faSchool,
		faBullseye,
		faUserShield,
		faLock,
		faClock,
		faFloppyDisk,
		faAddressCard,
		faRightToBracket,
		faMinus
	} from '@fortawesome/free-solid-svg-icons';
	const icons = {
		overview: faChartPie,
		promotions: faLayerGroup,
		accounts: faUsers,
		plus: faPlus,
		edit: faPen,
		archive: faBoxArchive,
		restore: faRotateLeft,
		search: faMagnifyingGlass,
		previous: faChevronLeft,
		next: faChevronRight,
		close: faXmark,
		email: faEnvelope,
		link: faLink,
		check: faCheck,
		student: faGraduationCap,
		teacher: faChalkboardUser,
		admin: faUserShield,
		arrow: faArrowRight,
		open: faArrowUpRightFromSquare,
		birthday: faCakeCandles,
		location: faLocationDot,
		phone: faPhone,
		school: faSchool,
		orientation: faBullseye,
		adult: faUserShield,
		lock: faLock,
		clock: faClock,
		save: faFloppyDisk,
		profile: faAddressCard,
		login: faRightToBracket,
		remove: faMinus
	};
	let { name, size = 18 }: { name: string; size?: number } = $props();
	const definition = $derived(
		(Object.hasOwn(icons, name) ? icons[name as keyof typeof icons] : icons.clock).icon
	);
	const paths = $derived(typeof definition[4] === 'string' ? [definition[4]] : definition[4]);
</script>

<svg
	width={size}
	height={size}
	viewBox={`0 0 ${definition[0]} ${definition[1]}`}
	fill="currentColor"
	aria-hidden="true"
	class="app-icon"
>
	{#each paths as path (path)}<path d={path} />{/each}
</svg>
