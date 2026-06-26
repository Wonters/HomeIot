const {access, presets} = require("zigbee-herdsman-converters/lib/exposes");
const m = require("zigbee-herdsman-converters/lib/modernExtend");
const definition = {
    zigbeeModel: ['linky'],
    model: 'linky',
    vendor: 'Shift',
    description: 'microchip',
    extend: [m.identify(),
        m.numeric({
            name: "power",
            cluster: "genAnalogValue",
            attribute: "presentValue",
            description: "Power",
            unit: "VA",
            access: "STATE",
            valueMin: 0,
            valueMax: 4000,
            valueStep: 1,
            reporting: {min: 0, max: 300, change: 1},
        }),
        m.numeric({
            name: "intensity",
            cluster: "genAnalogOutput",
            attribute: "presentValue",
            description: "Intensity",
            unit: "A",
            access: "STATE",
            valueMin: 0,
            valueMax: 40,
            valueStep: 1,
            reporting: null,
        }),
    ],
    ota: true
};
module.exports = definition;
