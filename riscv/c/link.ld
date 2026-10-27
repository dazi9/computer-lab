OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS
{
  . = 0x80000000;
  .text   : { KEEP(*(.text.start)) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) *(.srodata*) }
  .data   : { *(.data .data.*) *(.sdata*) }
  .bss    : { *(.bss .bss.*) *(.sbss*) *(COMMON) }
}
