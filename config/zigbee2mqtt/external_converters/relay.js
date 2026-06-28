const m = require("zigbee-herdsman-converters/lib/modernExtend");

const definition = {
    zigbeeModel: ["lightOnOff"],
    model: "relay-zigbee",
    vendor: "Shift",
    description: "ESP32-H2 Zigbee On/Off relay",
    extend: [
        m.deviceEndpoints({endpoints: {relay: 12}}),
        m.identify(),
        m.onOff({endpointNames: ["relay"], powerOnBehavior: false}),
    ],
};

module.exports = definition;
