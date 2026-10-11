// screenshot build only: stands in for ML Kit on web with the text of the sample customer DC photo
const TEXT = ['HYUNDAI MOTOR INDIA LTD', 'RETURNABLE PACKING - DELIVERY CHALLAN', 'DC No HM/RDC/24518 Date 11-10-2026', 'To Asahi India Glass Ltd, Chennai Plant',
  'Vehicle No TN 22 BX 7310 Driver Selvam', 'S.No Description Pallet No Qty', '1 Empty glass rack (non-folding) NF-8120 1', '2 Empty glass rack (non-folding) NF-8121 1', 'Total pallets 2'];
export default { recognize: async () => ({ text: TEXT.join('\n'), blocks: [{ lines: TEXT.map((text) => ({ text })) }] }) };
