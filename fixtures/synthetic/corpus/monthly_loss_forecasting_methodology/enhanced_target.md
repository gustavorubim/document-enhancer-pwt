# Monthly Loss Forecasting Methodology

Status: fictional evaluation target

## Purpose and scope

The method estimates monthly portfolio loss for the fictional Northstar Cooperative. It applies to the managed consumer portfolio and excludes one-off legal settlements.

## Data inputs and preparation

The analyst loads the Northstar ledger extract and delinquency history, removes duplicate account rows, and records the as-of date before modeling.

## Method and calculator

The method combines a three-month observed loss rate with a stress multiplier. The Loss Allocation Workbook is an offline Excel calculator owned by the Forecasting Lead.

## Controls and validation

The reviewer checks source row counts, recalculates the variance, and archives the workbook with the monthly evidence packet. A control is named but its frequency is not stated.

## Assumptions and limitations

The source assumes stable reporting definitions. It does not state how a structural portfolio change limits the result or who approves an override.

## Reviewer-approved fixture clarifications

- Q-FORECAST-001: The stress multiplier is dimensionless and the observed rate is a percentage over the three complete calendar months ending at the as-of date. (provenance: answer://fixture/Q-FORECAST-001)
- Q-FORECAST-002: Pause use when managed-portfolio composition changes by more than ten percent and obtain Forecasting Lead approval with the limitation recorded. (provenance: answer://fixture/Q-FORECAST-002)
