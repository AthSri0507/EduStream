package com.educationalstream;

/** A record does not satisfy the shared message contract (schemas/*.schema.json); it goes to the DLQ. */
public class ContractException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public ContractException(String message) {
        super(message);
    }
}
