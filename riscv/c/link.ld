OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS
{
  . = 0x80000000;
  .text   : { KEEP(*(.text.start)) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) *(.srodata*) }
  .data   : { *(.data .data.*) *(.sdata*) }
  .bss    : { *(.bss .bss.*) *(.sbss*) *(COMMON) }
  /* 裸机不展开栈帧:孤儿节 .eh_frame 会被 lld 随机排到 .text 前,必须显式丢弃 */
  /DISCARD/ : { *(.eh_frame*) *(.comment) *(.riscv.attributes) }
}
